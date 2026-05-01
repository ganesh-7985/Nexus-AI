#!/usr/bin/env python
# -*- coding: utf-8 -*-

import asyncio
import os
from typing import Optional

from google import genai
from google.genai.types import GenerateContentConfig

from metagpt.configs.llm_config import LLMConfig, LLMType
from metagpt.const import USE_CONFIG_TIMEOUT
from metagpt.logs import log_llm_stream, logger
from metagpt.provider.base_llm import BaseLLM
from metagpt.provider.llm_provider_registry import register_provider


@register_provider(LLMType.VERTEX)
class VertexAILLM(BaseLLM):
    """
    Google Gemini via Vertex AI (google-genai SDK).
    Uses GCP project credentials (ADC) instead of an API key.
    """

    def __init__(self, config: LLMConfig):
        self.use_system_prompt = False
        self.config = config
        self.model = config.model or "gemini-2.0-flash"
        self.pricing_plan = getattr(config, "pricing_plan", None) or self.model

        project_id = os.getenv("GCP_PROJECT_ID", "")
        location = os.getenv("GCP_LOCATION", "us-central1")

        if not project_id:
            raise ValueError(
                "GCP_PROJECT_ID env var is required for Vertex AI. "
                "Set it in backend/.env"
            )

        self.client = genai.Client(
            vertexai=True,
            project=project_id,
            location=location,
        )
        self.aclient = genai.Client(
            vertexai=True,
            project=project_id,
            location=location,
        )

        logger.info(
            f"Vertex AI (genai) initialized: project={project_id}, "
            f"location={location}, model={self.model}"
        )

    def _user_msg(self, msg: str, images=None) -> dict:
        return {"role": "user", "parts": [{"text": msg}]}

    def _assistant_msg(self, msg: str) -> dict:
        return {"role": "model", "parts": [{"text": msg}]}

    def _system_msg(self, msg: str) -> dict:
        return {"role": "user", "parts": [{"text": msg}]}

    def format_msg(self, messages) -> list[dict]:
        from metagpt.schema import Message

        if not isinstance(messages, list):
            messages = [messages]

        processed = []
        for msg in messages:
            if isinstance(msg, str):
                processed.append({"role": "user", "parts": [{"text": msg}]})
            elif isinstance(msg, dict):
                # Normalize: ensure parts have dict format
                if "parts" in msg and msg["parts"] and isinstance(msg["parts"][0], str):
                    msg = {**msg, "parts": [{"text": p} for p in msg["parts"]]}
                processed.append(msg)
            elif isinstance(msg, Message):
                processed.append({
                    "role": "user" if msg.role == "user" else "model",
                    "parts": [{"text": msg.content}],
                })
            else:
                raise ValueError(f"Unsupported message type: {type(msg).__name__}")
        return processed

    def get_choice_text(self, resp) -> str:
        return resp.text

    def get_usage(self, messages, resp_text: str) -> dict:
        prompt_tokens = sum(
            len(str(m)) // 4 for m in (messages if isinstance(messages, list) else [messages])
        )
        completion_tokens = len(resp_text) // 4
        return {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}

    async def aget_usage(self, messages, resp_text: str) -> dict:
        return self.get_usage(messages, resp_text)

    def _build_contents(self, messages: list[dict]) -> list:
        """Build contents suitable for google-genai SDK."""
        # The SDK can accept plain strings or structured content
        # For simplicity, concatenate user messages
        parts = []
        for msg in messages:
            if isinstance(msg, str):
                parts.append(msg)
            elif isinstance(msg, dict):
                role_parts = msg.get("parts", [])
                for p in role_parts:
                    if isinstance(p, str):
                        parts.append(p)
                    elif isinstance(p, dict) and "text" in p:
                        parts.append(p["text"])
        return "\n".join(parts) if parts else ""

    def completion(self, messages: list[dict]):
        contents = self._build_contents(messages)
        resp = self.client.models.generate_content(
            model=self.model,
            contents=contents,
            config=GenerateContentConfig(temperature=0.3),
        )
        usage = self.get_usage(messages, resp.text)
        self._update_costs(usage)
        return resp

    async def _retry_call(self, fn, *args, max_retries: int = 5, **kwargs):
        """Retry with exponential backoff for transient errors."""
        for attempt in range(max_retries):
            try:
                return await asyncio.to_thread(fn, *args, **kwargs)
            except Exception as e:
                err_str = str(e).lower()
                is_transient = any(k in err_str for k in [
                    "503", "unavailable", "overloaded", "high demand",
                    "rate", "resource_exhausted", "429", "quota",
                ])
                if is_transient and attempt < max_retries - 1:
                    wait = min(2 ** attempt * 2, 60)
                    logger.warning(
                        f"Vertex AI transient error (attempt {attempt+1}/{max_retries}), "
                        f"retrying in {wait}s: {e}"
                    )
                    await asyncio.sleep(wait)
                else:
                    raise

    async def _achat_completion(self, messages: list[dict], timeout: int = USE_CONFIG_TIMEOUT):
        contents = self._build_contents(messages)
        resp = await asyncio.wait_for(
            self._retry_call(
                self.client.models.generate_content,
                model=self.model,
                contents=contents,
                config=GenerateContentConfig(temperature=0.3),
            ),
            timeout=180,
        )
        usage = await self.aget_usage(messages, resp.text)
        self._update_costs(usage)
        return resp

    async def acompletion(self, messages: list[dict], timeout=USE_CONFIG_TIMEOUT) -> dict:
        return await self._achat_completion(messages, timeout=self.get_timeout(timeout))

    async def _achat_completion_stream(self, messages: list[dict], timeout: int = USE_CONFIG_TIMEOUT) -> str:
        contents = self._build_contents(messages)
        max_retries = 5
        call_timeout = 180  # 3 minute timeout per LLM call
        for attempt in range(max_retries):
            try:
                def _stream_and_collect():
                    """Run the entire stream in a thread so we don't block the event loop."""
                    resp_iter = self.client.models.generate_content_stream(
                        model=self.model,
                        contents=contents,
                        config=GenerateContentConfig(temperature=0.3),
                    )
                    collected = []
                    for chunk in resp_iter:
                        content = chunk.text
                        collected.append(content)
                    return "".join(collected)

                full = await asyncio.wait_for(
                    asyncio.to_thread(_stream_and_collect),
                    timeout=call_timeout,
                )
                log_llm_stream(full[:200] + "...\n" if len(full) > 200 else full + "\n")

                usage = await self.aget_usage(messages, full)
                self._update_costs(usage)
                return full
            except asyncio.TimeoutError:
                logger.warning(
                    f"Vertex AI stream timeout ({call_timeout}s) on attempt {attempt+1}/{max_retries}"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                else:
                    raise TimeoutError(f"Vertex AI did not respond within {call_timeout}s after {max_retries} attempts")
            except Exception as e:
                err_str = str(e).lower()
                is_transient = any(k in err_str for k in [
                    "503", "unavailable", "overloaded", "high demand",
                    "rate", "resource_exhausted", "429", "quota",
                ])
                if is_transient and attempt < max_retries - 1:
                    wait = min(2 ** attempt * 2, 60)
                    logger.warning(
                        f"Vertex AI stream error (attempt {attempt+1}/{max_retries}), "
                        f"retrying in {wait}s: {e}"
                    )
                    await asyncio.sleep(wait)
                else:
                    raise
