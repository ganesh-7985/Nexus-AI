#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Minimal shell_execute re-created after cleanup (original was in a larger shell module)."""

import asyncio
from typing import List, Optional, Tuple, Union


async def shell_execute(
    command: Union[str, List[str]],
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    timeout: Optional[int] = None,
) -> Tuple[str, str, int]:
    """Execute a shell command asynchronously and return (stdout, stderr, return_code)."""
    if isinstance(command, list):
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
    else:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise TimeoutError(f"Command timed out after {timeout}s")
    stdout = stdout_bytes.decode(errors="replace") if stdout_bytes else ""
    stderr = stderr_bytes.decode(errors="replace") if stderr_bytes else ""
    return stdout, stderr, proc.returncode or 0
