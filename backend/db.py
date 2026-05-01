"""
Nexus AI — Supabase database client and helper functions.
Provides persistent storage for projects, messages, and files.
"""

import os
from datetime import datetime, timezone
from typing import Optional

from supabase import create_client, Client

# ── Singleton client ────────────────────────────────────────────────
_client: Optional[Client] = None


def get_client() -> Client:
    """Return the Supabase client singleton. Lazily initialized."""
    global _client
    if _client is None:
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_SERVICE_KEY", "")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in backend/.env"
            )
        _client = create_client(url, key)
    return _client


# ── Profiles ────────────────────────────────────────────────────────

def get_profile(user_id: str) -> Optional[dict]:
    sb = get_client()
    res = sb.table("profiles").select("*").eq("id", user_id).execute()
    return res.data[0] if res.data else None


def upsert_profile(user_id: str, email: str, display_name: str = "", avatar_url: str = ""):
    sb = get_client()
    sb.table("profiles").upsert({
        "id": user_id,
        "email": email,
        "display_name": display_name or email.split("@")[0],
        "avatar_url": avatar_url,
    }).execute()


# ── Projects ────────────────────────────────────────────────────────

def create_project(project_id: str, user_id: str, name: str, prompt: str) -> dict:
    sb = get_client()
    row = {
        "id": project_id,
        "user_id": user_id,
        "name": name,
        "prompt": prompt,
        "status": "created",
    }
    res = sb.table("projects").insert(row).execute()
    return res.data[0] if res.data else row


def get_project(project_id: str, user_id: str = None) -> Optional[dict]:
    sb = get_client()
    q = sb.table("projects").select("*").eq("id", project_id)
    if user_id:
        q = q.eq("user_id", user_id)
    res = q.execute()
    return res.data[0] if res.data else None


def list_projects(user_id: str) -> list[dict]:
    sb = get_client()
    res = (
        sb.table("projects")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


def update_project(project_id: str, updates: dict) -> Optional[dict]:
    sb = get_client()
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    res = sb.table("projects").update(updates).eq("id", project_id).execute()
    return res.data[0] if res.data else None


def delete_project(project_id: str):
    sb = get_client()
    sb.table("projects").delete().eq("id", project_id).execute()


# ── Messages ────────────────────────────────────────────────────────

def save_message(project_id: str, role: str, content: str, agent_name: str = ""):
    sb = get_client()
    sb.table("messages").insert({
        "project_id": project_id,
        "role": role,
        "agent_name": agent_name,
        "content": content,
    }).execute()


def get_messages(project_id: str) -> list[dict]:
    sb = get_client()
    res = (
        sb.table("messages")
        .select("*")
        .eq("project_id", project_id)
        .order("created_at", desc=False)
        .execute()
    )
    return res.data or []


# ── Files ───────────────────────────────────────────────────────────

def save_file(project_id: str, path: str, content: str, size: int = 0):
    sb = get_client()
    sb.table("files").upsert({
        "project_id": project_id,
        "path": path,
        "content": content,
        "size": size or len(content.encode("utf-8", errors="replace")),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="project_id,path").execute()


def get_files(project_id: str) -> list[dict]:
    sb = get_client()
    res = (
        sb.table("files")
        .select("*")
        .eq("project_id", project_id)
        .order("path", desc=False)
        .execute()
    )
    return res.data or []


def get_file(project_id: str, path: str) -> Optional[dict]:
    sb = get_client()
    res = (
        sb.table("files")
        .select("*")
        .eq("project_id", project_id)
        .eq("path", path)
        .execute()
    )
    return res.data[0] if res.data else None


def save_files_bulk(project_id: str, files: list[dict]):
    """Save multiple files at once. Each dict needs 'path' and 'content'."""
    sb = get_client()
    rows = []
    for f in files:
        rows.append({
            "project_id": project_id,
            "path": f["path"],
            "content": f["content"],
            "size": f.get("size", len(f["content"].encode("utf-8", errors="replace"))),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
    if rows:
        sb.table("files").upsert(rows, on_conflict="project_id,path").execute()
