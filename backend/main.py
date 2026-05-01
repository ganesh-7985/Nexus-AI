"""
Nexus AI — FastAPI backend server
Wraps the cleaned MetaGPT pipeline and exposes REST + WebSocket endpoints.
Includes a Publish feature to download generated code as ZIP or deploy to Netlify.
"""

import asyncio
import io
import json
import os
import shutil
import subprocess
import sys
import traceback
import uuid
import zipfile
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv, set_key
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse, Response, JSONResponse
from pydantic import BaseModel

import db
import containers
from auth import get_user_id_from_request, get_user_id_from_ws, get_optional_user_id
from builders import detect_framework, get_framework_display_name

# ── Load env ──────────────────────────────────────────────────────────
ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_PATH)

# ── Inject MetaGPT onto sys.path ─────────────────────────────────────
METAGPT_ROOT = Path(__file__).resolve().parent.parent / "MetaGPT"
WORKSPACE_ROOT = METAGPT_ROOT / "workspace"
if str(METAGPT_ROOT) not in sys.path:
    sys.path.insert(0, str(METAGPT_ROOT))

# ── FastAPI app ───────────────────────────────────────────────────────
app = FastAPI(title="Nexus AI Backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory fallback for workspace paths (transient, per-run) ─────
_workspace_cache: dict = {}

# ── Published sites directory ────────────────────────────────────────
PUBLISH_DIR = Path(__file__).resolve().parent / "published_sites"
PUBLISH_DIR.mkdir(exist_ok=True)


# ── Schemas ──────────────────────────────────────────────────────────
class ProjectCreate(BaseModel):
    prompt: str
    name: Optional[str] = None
    investment: float = float(os.getenv("INVESTMENT", "3.0"))
    n_round: int = int(os.getenv("N_ROUND", "5"))


class ProjectOut(BaseModel):
    id: str
    name: str
    prompt: str
    status: str


class ConfigUpdate(BaseModel):
    api_type: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None
    gcp_project_id: Optional[str] = None
    gcp_location: Optional[str] = None


# ── REST endpoints ───────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/config")
async def get_config():
    """Return current LLM configuration (no secrets)."""
    return {
        "api_type": os.getenv("LLM_API_TYPE", "gemini"),
        "model": os.getenv("LLM_MODEL", "gemini-1.5-flash"),
        "base_url": os.getenv("LLM_BASE_URL", ""),
        "has_key": bool(os.getenv("LLM_API_KEY", ""))
        and os.getenv("LLM_API_KEY") != "your-api-key-here",
        "gcp_project_id": os.getenv("GCP_PROJECT_ID", ""),
        "gcp_location": os.getenv("GCP_LOCATION", "us-central1"),
    }


@app.put("/api/config")
async def update_config(body: ConfigUpdate):
    """Update LLM config and persist to .env file."""
    mapping = {
        "api_type": "LLM_API_TYPE",
        "api_key": "LLM_API_KEY",
        "model": "LLM_MODEL",
        "base_url": "LLM_BASE_URL",
        "gcp_project_id": "GCP_PROJECT_ID",
        "gcp_location": "GCP_LOCATION",
    }
    for field, env_var in mapping.items():
        value = getattr(body, field, None)
        if value is not None:
            os.environ[env_var] = value
            set_key(str(ENV_PATH), env_var, value)
    return {"status": "ok"}


@app.post("/api/projects", response_model=ProjectOut)
async def create_project(body: ProjectCreate, request: Request):
    user_id = get_user_id_from_request(request)
    pid = str(uuid.uuid4())[:8]
    proj = db.create_project(pid, user_id, body.name or body.prompt[:40], body.prompt)
    return {
        "id": proj["id"],
        "name": proj["name"],
        "prompt": proj["prompt"],
        "status": proj["status"],
    }


@app.get("/api/projects")
async def list_projects_endpoint(request: Request):
    user_id = get_user_id_from_request(request)
    rows = db.list_projects(user_id)
    return rows


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str, request: Request):
    user_id = get_user_id_from_request(request)
    proj = db.get_project(project_id, user_id)
    if not proj:
        return JSONResponse({"error": "not found"}, status_code=404)
    return proj


@app.delete("/api/projects/{project_id}")
async def delete_project_endpoint(project_id: str, request: Request):
    user_id = get_user_id_from_request(request)
    proj = db.get_project(project_id, user_id)
    if not proj:
        return JSONResponse({"error": "not found"}, status_code=404)
    db.delete_project(project_id)
    # Clean up published files
    pub_dir = PUBLISH_DIR / project_id
    if pub_dir.exists():
        shutil.rmtree(pub_dir)
    return {"status": "deleted"}


@app.get("/api/projects/{project_id}/messages")
async def get_project_messages(project_id: str, request: Request):
    """Get all messages for a project."""
    user_id = get_user_id_from_request(request)
    proj = db.get_project(project_id, user_id)
    if not proj:
        return JSONResponse({"error": "Project not found"}, status_code=404)
    return db.get_messages(project_id)


# ── Publish: download generated code as ZIP ──────────────────────────
@app.get("/api/projects/{project_id}/download")
async def download_project(project_id: str, request: Request):
    """Download the generated project workspace as a ZIP file."""
    user_id = get_user_id_from_request(request)
    proj = db.get_project(project_id, user_id)
    if not proj:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    ws_path = proj.get("workspace_path", "") or _workspace_cache.get(project_id, "")
    if not ws_path or not Path(ws_path).exists():
        ws_path = _find_workspace(project_id)
        if not ws_path:
            return JSONResponse({"error": "No generated files found. Run the pipeline first."}, status_code=404)

    zip_buffer = io.BytesIO()
    root = Path(ws_path)
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in root.rglob("*"):
            if file.is_file() and ".git" not in file.parts:
                zf.write(file, file.relative_to(root))

    zip_buffer.seek(0)
    filename = f"{proj['name'][:30].replace(' ', '_')}.zip"
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/projects/{project_id}/files")
async def list_project_files(project_id: str, request: Request):
    """List all generated files for a project."""
    user_id = get_user_id_from_request(request)
    proj = db.get_project(project_id, user_id)
    if not proj:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    ws_path = proj.get("workspace_path", "") or _workspace_cache.get(project_id, "")
    if not ws_path or not Path(ws_path).exists():
        ws_path = _find_workspace(project_id)

    # ── Try filesystem ──
    if ws_path and Path(ws_path).exists():
        root = Path(ws_path)
        files = []
        for f in sorted(root.rglob("*")):
            if f.is_file() and ".git" not in f.parts:
                rel = str(f.relative_to(root))
                try:
                    content = f.read_text(errors="replace")[:5000]
                except Exception:
                    content = "(binary file)"
                files.append({"path": rel, "size": f.stat().st_size, "content": content})
        return {"files": files, "workspace": str(ws_path)}

    # ── Fallback: serve from DB ──
    db_files = db.get_files(project_id)
    if db_files:
        files = [
            {"path": f["path"], "size": f.get("size", 0), "content": (f.get("content") or "")[:5000]}
            for f in db_files
        ]
        return {"files": files, "workspace": "(stored in database)"}

    return {"files": []}


@app.post("/api/projects/{project_id}/publish")
async def publish_project(project_id: str, request: Request):
    """
    Publish the generated project — for JS apps, build inside Docker and
    copy the dist/ output. For other frameworks, copy source as-is.
    """
    user_id = get_user_id_from_request(request)
    proj = db.get_project(project_id, user_id)
    if not proj:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    ws_path = proj.get("workspace_path", "") or _workspace_cache.get(project_id, "")
    if not ws_path or not Path(ws_path).exists():
        ws_path = _find_workspace(project_id)
        if not ws_path:
            return JSONResponse({"error": "No generated files. Run the pipeline first."}, status_code=404)

    pub_dir = PUBLISH_DIR / project_id
    if pub_dir.exists():
        shutil.rmtree(pub_dir)

    # Detect framework and find code directory
    from builders import detect_framework
    from containers import _find_code_dir, _scaffold_react_project
    framework = detect_framework(Path(ws_path))

    if framework in ("react", "vue", "nextjs"):
        code_dir = _find_code_dir(Path(ws_path))
        _scaffold_react_project(code_dir, Path(ws_path))
        # Build inside Docker
        try:
            import docker
            client = docker.from_env()
            image_tag = f"nexus-build-{project_id}:latest"
            # Build using the same React Dockerfile
            from builders import get_dockerfile_content
            dockerfile_content = get_dockerfile_content(framework)
            (code_dir / "Dockerfile").write_text(dockerfile_content)
            (code_dir / ".dockerignore").write_text("node_modules\n.git\n__pycache__\n*.pyc\n.env\n")
            client.images.build(path=str(code_dir), tag=image_tag, rm=True, forcerm=True)
            # Ensure output dir exists before mounting
            pub_dir.mkdir(parents=True, exist_ok=True)
            # Run vite build inside the container and copy dist/ out
            build_container = client.containers.run(
                image_tag,
                command="sh -c 'npx vite build --base=./ 2>&1 && cp -r dist/* /output/ 2>/dev/null || cp -r build/* /output/ 2>/dev/null || echo NO_BUILD_OUTPUT'",
                volumes={str(pub_dir): {"bind": "/output", "mode": "rw"}},
                remove=True,
            )
            print(f"[PUBLISH] Build output: {build_container.decode()[:500] if isinstance(build_container, bytes) else str(build_container)[:500]}")
            # Clean up
            (code_dir / "Dockerfile").unlink(missing_ok=True)
            (code_dir / ".dockerignore").unlink(missing_ok=True)
            try:
                client.images.remove(image_tag, force=True)
            except Exception:
                pass
        except Exception as e:
            print(f"[PUBLISH] Docker build failed, falling back to raw copy: {e}")
            if pub_dir.exists():
                shutil.rmtree(pub_dir)
            shutil.copytree(ws_path, pub_dir)
    else:
        shutil.copytree(ws_path, pub_dir)

    # Ensure pub_dir exists (Docker build creates it via volume mount)
    pub_dir.mkdir(parents=True, exist_ok=True)

    # Fix absolute asset paths in index.html → relative paths
    _fix_published_asset_paths(pub_dir)

    preview_url = f"/published/{project_id}/"
    db.update_project(project_id, {"published_url": preview_url, "status": "published"})

    return {
        "status": "published",
        "download_url": f"/api/projects/{project_id}/download",
        "files_url": f"/api/projects/{project_id}/files",
        "workspace": ws_path,
        "preview_url": preview_url,
    }


class FileUpdate(BaseModel):
    content: str


@app.put("/api/projects/{project_id}/file")
async def update_project_file(project_id: str, body: FileUpdate, path: str = "", request: Request = None):
    """Update the content of a single file in the project workspace."""
    user_id = get_user_id_from_request(request) if request else None
    proj = db.get_project(project_id, user_id)
    if not proj:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    ws_path = proj.get("workspace_path", "") or _workspace_cache.get(project_id, "")
    if not ws_path or not Path(ws_path).exists():
        ws_path = _find_workspace(project_id)
        if not ws_path:
            return JSONResponse({"error": "No workspace found"}, status_code=404)

    target = Path(ws_path) / path
    if not target.exists():
        return JSONResponse({"error": f"File not found: {path}"}, status_code=404)

    target.write_text(body.content, encoding="utf-8")

    # Also update published copy if it exists
    pub_file = PUBLISH_DIR / project_id / path
    if pub_file.exists():
        pub_file.write_text(body.content, encoding="utf-8")

    # Persist to DB
    db.save_file(project_id, path, body.content)

    return {"status": "ok", "path": path}


# ── Serve preview: static files from workspace ───────────────────────
@app.get("/preview/{project_id}/{file_path:path}")
async def preview_file(project_id: str, file_path: str):
    """Serve files from a project workspace for iframe preview (public, no auth needed).
    Falls back to serving from DB-stored files when filesystem workspace is missing."""
    import mimetypes

    proj = db.get_project(project_id)
    ws_path = None
    if proj:
        ws_path = proj.get("workspace_path", "") or _workspace_cache.get(project_id, "")
    if not ws_path or not Path(ws_path).exists():
        ws_path = _workspace_cache.get(project_id) or _find_workspace(project_id)

    # If no file_path or directory, serve index.html
    if not file_path or file_path == "/":
        file_path = "index.html"

    # ── Try serving from filesystem ──
    if ws_path and Path(ws_path).exists():
        root = Path(ws_path)

        # For React/Vue/Next.js projects, raw source files won't render in a
        # browser. Show a helpful page directing users to Docker Preview or Publish.
        if file_path == "index.html":
            from builders import detect_framework
            from containers import _find_code_dir
            code_dir = _find_code_dir(root)
            framework = detect_framework(code_dir)
            if framework in ("react", "vue", "nextjs"):
                return HTMLResponse(_framework_preview_page(framework, project_id))

        target = root / file_path
        if not target.exists() or not target.is_file():
            for subdir in ["", "src", "public", "dist", "build"]:
                candidate = root / subdir / file_path if subdir else root / file_path
                if candidate.exists() and candidate.is_file():
                    target = candidate
                    break
            else:
                if file_path == "index.html":
                    return HTMLResponse(_generate_preview_index(root, project_id))
                return Response(f"File not found: {file_path}", status_code=404)

        content_type, _ = mimetypes.guess_type(str(target))
        return FileResponse(str(target), media_type=content_type or "application/octet-stream")

    # ── Fallback: serve from DB-stored files ──
    db_file = db.get_file(project_id, file_path)
    if db_file:
        content_type, _ = mimetypes.guess_type(file_path)
        return Response(
            content=db_file["content"],
            media_type=content_type or "text/plain",
        )

    # Try to generate an index from DB files
    if file_path == "index.html":
        db_files = db.get_files(project_id)
        if db_files:
            return HTMLResponse(_generate_db_preview_index(db_files, project_id))

    return Response("No workspace found. Re-run the pipeline to regenerate.", status_code=404)


# ── Serve published site ─────────────────────────────────────────────
@app.get("/published/{project_id}/{file_path:path}")
async def published_file(project_id: str, file_path: str):
    """Serve files from a published project. Falls back to DB files."""
    import mimetypes

    pub_dir = PUBLISH_DIR / project_id

    if not file_path or file_path == "/":
        file_path = "index.html"

    # ── Try filesystem published dir ──
    if pub_dir.exists():
        target = pub_dir / file_path
        if target.exists() and target.is_file():
            content_type, _ = mimetypes.guess_type(str(target))
            return FileResponse(str(target), media_type=content_type or "application/octet-stream")
        if file_path == "index.html":
            return HTMLResponse(_generate_preview_index(pub_dir, project_id))
        return Response(f"File not found: {file_path}", status_code=404)

    # ── Fallback: serve from DB-stored files ──
    db_file = db.get_file(project_id, file_path)
    if db_file:
        content_type, _ = mimetypes.guess_type(file_path)
        return Response(content=db_file["content"], media_type=content_type or "text/plain")

    if file_path == "index.html":
        db_files = db.get_files(project_id)
        if db_files:
            return HTMLResponse(_generate_db_preview_index(db_files, project_id))

    return Response("Not published yet", status_code=404)


def _generate_db_preview_index(db_files: list[dict], project_id: str) -> str:
    """Generate a preview HTML page from DB-stored files (when filesystem is gone)."""
    file_links = ""
    for f in db_files:
        path = f["path"]
        file_links += f'<li><a href="/preview/{project_id}/{path}">{path}</a></li>\n'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Project Preview</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
               background: #0a0a0a; color: #e5e5e5; padding: 2rem; }}
        h1 {{ font-size: 1.5rem; margin-bottom: 0.5rem; }}
        p {{ color: #888; margin-bottom: 1.5rem; font-size: 0.9rem; }}
        ul {{ list-style: none; }}
        li {{ padding: 0.4rem 0; border-bottom: 1px solid #1a1a1a; }}
        a {{ color: #60a5fa; text-decoration: none; font-family: monospace; font-size: 0.85rem; }}
        a:hover {{ text-decoration: underline; }}
        .badge {{ display: inline-block; background: #1e3a5f; color: #93c5fd;
                 padding: 2px 8px; border-radius: 4px; font-size: 0.7rem; margin-left: 8px; }}
    </style>
</head>
<body>
    <h1>📦 Generated Project (from saved files)</h1>
    <p>{len(db_files)} files stored</p>
    <ul>{file_links}</ul>
</body>
</html>"""


def _generate_preview_index(root: Path, project_id: str) -> str:
    """Generate a preview HTML page that shows the project files."""
    # Look for any HTML files
    html_files = list(root.rglob("*.html"))
    py_files = list(root.rglob("*.py"))
    js_files = list(root.rglob("*.js")) + list(root.rglob("*.ts")) + list(root.rglob("*.tsx"))

    file_links = ""
    all_files = sorted(root.rglob("*"))
    for f in all_files:
        if f.is_file() and ".git" not in f.parts:
            rel = f.relative_to(root)
            file_links += f'<li><a href="/preview/{project_id}/{rel}">{rel}</a></li>\n'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Project Preview</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
               background: #0a0a0a; color: #e5e5e5; padding: 2rem; }}
        h1 {{ font-size: 1.5rem; margin-bottom: 0.5rem; }}
        p {{ color: #888; margin-bottom: 1.5rem; font-size: 0.9rem; }}
        ul {{ list-style: none; }}
        li {{ padding: 0.4rem 0; border-bottom: 1px solid #1a1a1a; }}
        a {{ color: #60a5fa; text-decoration: none; font-family: monospace; font-size: 0.85rem; }}
        a:hover {{ text-decoration: underline; }}
        .badge {{ display: inline-block; background: #1e3a5f; color: #93c5fd;
                 padding: 2px 8px; border-radius: 4px; font-size: 0.7rem; margin-left: 8px; }}
    </style>
</head>
<body>
    <h1>📦 Generated Project</h1>
    <p>{len(list(root.rglob('*')))} files generated</p>
    <ul>{file_links}</ul>
</body>
</html>"""


# ── Container preview endpoints ──────────────────────────────────────

@app.post("/api/projects/{project_id}/container/start")
async def start_container_preview(project_id: str, request: Request):
    """Build and start a Docker container for live preview."""
    user_id = get_user_id_from_request(request)
    proj = db.get_project(project_id, user_id)
    if not proj:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    ws_path = proj.get("workspace_path", "") or _workspace_cache.get(project_id, "")
    if not ws_path or not Path(ws_path).exists():
        ws_path = _find_workspace(project_id)

    # If filesystem workspace is gone, reconstruct from DB files
    if not ws_path or not Path(ws_path).exists():
        db_files = db.get_files(project_id)
        if db_files:
            ws_path = str(WORKSPACE_ROOT / f"restored_{project_id}")
            _restore_workspace_from_db(ws_path, db_files)
            _workspace_cache[project_id] = ws_path
            db.update_project(project_id, {"workspace_path": ws_path})
        else:
            return JSONResponse({"error": "No workspace found. Re-run the pipeline."}, status_code=404)

    result = containers.start_preview(project_id, ws_path)
    if result.get("status") == "running":
        db.update_project(project_id, {"framework": result.get("framework", "")})
    return result


@app.post("/api/projects/{project_id}/container/stop")
async def stop_container_preview(project_id: str, request: Request):
    """Stop the preview container for a project."""
    user_id = get_user_id_from_request(request)
    proj = db.get_project(project_id, user_id)
    if not proj:
        return JSONResponse({"error": "Project not found"}, status_code=404)
    return containers.stop_preview(project_id)


@app.get("/api/projects/{project_id}/container/status")
async def container_status(project_id: str, request: Request):
    """Get the status of a project's preview container."""
    user_id = get_user_id_from_request(request)
    proj = db.get_project(project_id, user_id)
    if not proj:
        return JSONResponse({"error": "Project not found"}, status_code=404)
    return containers.get_preview_status(project_id)


@app.get("/api/projects/{project_id}/container/logs")
async def container_logs(project_id: str, request: Request, tail: int = 100):
    """Get logs from a project's preview container."""
    user_id = get_user_id_from_request(request)
    proj = db.get_project(project_id, user_id)
    if not proj:
        return JSONResponse({"error": "Project not found"}, status_code=404)
    logs = containers.get_container_logs(project_id, tail=tail)
    return {"logs": logs}


@app.get("/api/projects/{project_id}/container/view/{file_path:path}")
@app.get("/api/projects/{project_id}/container/view")
async def container_proxy(project_id: str, request: Request, file_path: str = ""):
    """Proxy requests to the running Docker container.
    If the container server isn't ready yet, serve a loading page that auto-refreshes."""
    import httpx

    with containers._lock:
        info = containers._active.get(project_id)

    if not info:
        return HTMLResponse(
            _container_loading_page("Container not running. Click 'Docker Preview' to start."),
            status_code=503,
        )

    port = info["port"]
    target_url = f"http://localhost:{port}/{file_path}"

    # Try proxying to the container
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(target_url, follow_redirects=True)
        # Forward the response
        excluded_headers = {"transfer-encoding", "content-encoding", "connection"}
        headers = {
            k: v for k, v in resp.headers.items()
            if k.lower() not in excluded_headers
        }
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=headers,
            media_type=resp.headers.get("content-type", "text/html"),
        )
    except Exception:
        # Container is running but server isn't ready yet — show loading page
        return HTMLResponse(_container_loading_page("Starting up... this page will auto-refresh."))


@app.get("/api/projects/{project_id}/container/ready")
async def container_ready_check(project_id: str):
    """Quick health check to see if the container's web server is responding."""
    import httpx

    with containers._lock:
        info = containers._active.get(project_id)

    if not info:
        return {"ready": False, "reason": "not_running"}

    port = info["port"]
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"http://localhost:{port}/", follow_redirects=True)
        return {"ready": resp.status_code < 500, "port": port}
    except Exception:
        return {"ready": False, "reason": "not_responding"}


def _container_loading_page(message: str = "Loading...") -> str:
    """Auto-refreshing loading page shown while container boots."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="refresh" content="3" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Loading Preview...</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ display: flex; align-items: center; justify-content: center; min-height: 100vh;
           font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
           background: #0a0a0a; color: #e5e5e5; }}
    .card {{ text-align: center; padding: 3rem; }}
    .spinner {{ width: 40px; height: 40px; border: 3px solid #333; border-top-color: #60a5fa;
               border-radius: 50%; animation: spin 0.8s linear infinite; margin: 0 auto 1.5rem; }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    h2 {{ font-size: 1.2rem; font-weight: 600; margin-bottom: 0.5rem; }}
    p {{ color: #888; font-size: 0.85rem; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="spinner"></div>
    <h2>Building Preview</h2>
    <p>{message}</p>
  </div>
</body>
</html>"""


@app.get("/api/projects/{project_id}/framework")
async def get_project_framework(project_id: str, request: Request):
    """Detect and return the framework of a generated project."""
    user_id = get_user_id_from_request(request)
    proj = db.get_project(project_id, user_id)
    if not proj:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    ws_path = proj.get("workspace_path", "") or _workspace_cache.get(project_id, "")
    if not ws_path or not Path(ws_path).exists():
        ws_path = _find_workspace(project_id)
        if not ws_path:
            return {"framework": "unknown", "display_name": "Unknown"}

    framework = detect_framework(Path(ws_path))
    display_name = get_framework_display_name(framework)
    return {"framework": framework, "display_name": display_name}


# ── Cleanup containers on shutdown ───────────────────────────────────
@app.on_event("shutdown")
async def shutdown_cleanup():
    containers.cleanup_all()


def _framework_preview_page(framework: str, project_id: str) -> str:
    """Show a helpful page for React/Vue/Next.js projects that can't render as static files."""
    fw_names = {"react": "React", "vue": "Vue", "nextjs": "Next.js"}
    fw_name = fw_names.get(framework, framework.title())
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{fw_name} App — Preview</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ display: flex; align-items: center; justify-content: center; min-height: 100vh;
           font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
           background: #0a0a0a; color: #e5e5e5; }}
    .card {{ text-align: center; padding: 3rem; max-width: 480px; }}
    .icon {{ font-size: 3rem; margin-bottom: 1rem; }}
    h2 {{ font-size: 1.4rem; font-weight: 700; margin-bottom: 0.5rem; }}
    p {{ color: #888; font-size: 0.9rem; line-height: 1.6; margin-bottom: 1.5rem; }}
    .badge {{ display: inline-block; background: #1e3a5f; color: #93c5fd;
             padding: 4px 12px; border-radius: 6px; font-size: 0.8rem; font-weight: 600;
             margin-bottom: 1.5rem; }}
    .steps {{ text-align: left; background: #111; border-radius: 12px; padding: 1.5rem;
             border: 1px solid #222; }}
    .step {{ display: flex; align-items: flex-start; gap: 0.75rem; margin-bottom: 1rem; }}
    .step:last-child {{ margin-bottom: 0; }}
    .num {{ background: #60a5fa; color: #0a0a0a; width: 24px; height: 24px; border-radius: 50%;
           display: flex; align-items: center; justify-content: center; font-size: 0.75rem;
           font-weight: 700; flex-shrink: 0; margin-top: 2px; }}
    .step-text {{ font-size: 0.85rem; color: #ccc; }}
    .step-text strong {{ color: #e5e5e5; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">⚛️</div>
    <span class="badge">{fw_name} App Detected</span>
    <h2>This app needs a build step</h2>
    <p>{fw_name} apps use JSX and modules that browsers can't run directly.
       Use one of these options to see your app:</p>
    <div class="steps">
      <div class="step">
        <span class="num">1</span>
        <span class="step-text"><strong>Docker Preview</strong> — Click the "Docker Preview"
          button in the toolbar. This runs a Vite dev server inside a container.</span>
      </div>
      <div class="step">
        <span class="num">2</span>
        <span class="step-text"><strong>Publish</strong> — Click "Publish" to build the app
          with Vite and get a working preview link.</span>
      </div>
    </div>
  </div>
</body>
</html>"""


def _fix_published_asset_paths(pub_dir: Path):
    """Rewrite absolute asset paths in index.html to relative paths.
    Vite builds with absolute paths like /assets/... which break when
    served under /published/{id}/. This converts them to ./assets/..."""
    import re
    index_file = pub_dir / "index.html"
    if not index_file.exists():
        return
    try:
        html = index_file.read_text(encoding="utf-8")
        # Replace src="/assets/..." → src="./assets/..."
        # Replace href="/assets/..." → href="./assets/..."
        fixed = re.sub(r'(src|href)="(/)', r'\1="./', html)
        if fixed != html:
            index_file.write_text(fixed, encoding="utf-8")
            print(f"[PUBLISH] Fixed asset paths in {index_file}")
    except Exception as e:
        print(f"[PUBLISH] Failed to fix asset paths: {e}")


def _restore_workspace_from_db(ws_path: str, db_files: list[dict]):
    """Reconstruct a workspace directory from DB-stored files."""
    root = Path(ws_path)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    for f in db_files:
        file_path = root / f["path"]
        file_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            file_path.write_text(f.get("content", ""), encoding="utf-8")
        except Exception as e:
            print(f"[RESTORE] Failed to write {f['path']}: {e}")
    print(f"[RESTORE] Restored {len(db_files)} files to {ws_path}")


def _find_workspace(project_id: str) -> str:
    """Search WORKSPACE_ROOT for the latest project directory."""
    if not WORKSPACE_ROOT.exists():
        return ""
    # MetaGPT creates dirs by project name; find the most recent one
    dirs = sorted(
        [d for d in WORKSPACE_ROOT.iterdir() if d.is_dir() and d.name != "storage"],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    if dirs:
        return str(dirs[0])
    return ""


# ── Pipeline concurrency guard ─────────────────────────────────────
_pipeline_lock = asyncio.Lock()
_active_pipeline: str | None = None

# ── WebSocket: run pipeline with real-time streaming ─────────────────
@app.websocket("/ws/run/{project_id}")
async def ws_run_pipeline(ws: WebSocket, project_id: str):
    global _active_pipeline
    await ws.accept()

    # Send immediate confirmation that WS is connected
    try:
        await ws.send_json({"type": "connected", "project_id": project_id})
    except Exception:
        pass

    # Authenticate via query param
    try:
        user_id = get_user_id_from_ws(ws)
    except Exception:
        await ws.send_json({"type": "error", "message": "Authentication required"})
        await ws.close()
        return

    proj = db.get_project(project_id, user_id)
    if not proj:
        await ws.send_json({"type": "error", "message": "Project not found"})
        await ws.close()
        return

    prompt = proj["prompt"]
    investment = float(os.getenv("INVESTMENT", "6.0"))
    n_round = int(os.getenv("N_ROUND", "25"))
    print(f"[CONFIG] investment={investment}, n_round={n_round}")

    # Prevent concurrent pipeline runs
    if _active_pipeline:
        try:
            await ws.send_json({"type": "error", "message": f"Another pipeline is already running (project {_active_pipeline}). Please wait."})
        except Exception:
            pass
        try:
            await ws.close()
        except Exception:
            pass
        return

    _active_pipeline = project_id
    db.update_project(project_id, {"status": "running"})

    try:
        workspace_path = await _run_metagpt_pipeline(
            ws, prompt, investment, n_round, project_id
        )
        db.update_project(project_id, {"status": "completed", "workspace_path": workspace_path or ""})
        _workspace_cache[project_id] = workspace_path or ""

        # Persist generated files to DB
        if workspace_path and Path(workspace_path).exists():
            _persist_files_to_db(project_id, workspace_path)

        await ws.send_json({
            "type": "complete",
            "workspace_path": workspace_path or "",
        })
    except WebSocketDisconnect:
        db.update_project(project_id, {"status": "disconnected"})
    except Exception as e:
        db.update_project(project_id, {"status": "error"})
        tb = traceback.format_exc()
        print(f"[PIPELINE] Error: {e}\n{tb}")
        try:
            await ws.send_json({"type": "error", "message": str(e)[:500], "traceback": tb})
        except Exception:
            pass
    finally:
        _active_pipeline = None
        try:
            await ws.close()
        except Exception:
            pass


def _persist_files_to_db(project_id: str, workspace_path: str):
    """Save all generated files from workspace to Supabase."""
    root = Path(workspace_path)
    files = []
    for f in root.rglob("*"):
        if f.is_file() and ".git" not in f.parts:
            try:
                content = f.read_text(errors="replace")[:50000]
            except Exception:
                content = "(binary file)"
            files.append({
                "path": str(f.relative_to(root)),
                "content": content,
                "size": f.stat().st_size,
            })
    if files:
        db.save_files_bulk(project_id, files)


async def _run_metagpt_pipeline(
    ws: WebSocket, prompt: str, investment: float, n_round: int, project_id: str
) -> str:
    """
    Run the MetaGPT team pipeline.
    Patches the environment to intercept messages and stream them over WS.
    Returns the workspace path where files were generated.
    """
    # ── Build config on the fly from env vars ────────────────────────
    from metagpt.configs.llm_config import LLMConfig, LLMType
    from metagpt.config2 import Config

    api_type_str = os.getenv("LLM_API_TYPE", "openai")
    api_key = os.getenv("LLM_API_KEY", "")
    model = os.getenv("LLM_MODEL", "gpt-4o")
    base_url = os.getenv("LLM_BASE_URL", "")

    llm_type_map = {
        "openai": LLMType.OPENAI,
        "gemini": LLMType.GEMINI,
        "vertex": LLMType.VERTEX,
        "anthropic": LLMType.ANTHROPIC,
        "claude": LLMType.CLAUDE,
        "azure": LLMType.AZURE,
    }
    api_type = llm_type_map.get(api_type_str, LLMType.OPENAI)

    llm_kwargs = {
        "api_type": api_type,
        "api_key": api_key or "vertex-uses-adc",  # Vertex AI uses ADC, not API key
        "model": model,
    }
    if base_url:
        llm_kwargs["base_url"] = base_url

    llm_config = LLMConfig(**llm_kwargs)
    cfg = Config(llm=llm_config)

    from metagpt.context import Context
    from metagpt.roles import (
        Architect,
        Engineer,
        ProductManager,
        ProjectManager,
        QaEngineer,
    )
    from metagpt.team import Team

    ctx = Context(config=cfg)
    company = Team(context=ctx)
    company.hire(
        [
            ProductManager(),
            Architect(),
            ProjectManager(),
            Engineer(n_borg=5, use_code_review=True),
            QaEngineer(),
        ]
    )

    # Force all roles to re-init their LLM from the correct context/config.
    # Roles cache their LLM during __init__ (before context is set by hire),
    # so we must clear the cached LLM so it re-creates from the team's config.
    for role in company.env.roles.values():
        role.private_llm = None
        # Also reset LLM on each action owned by the role
        for action in getattr(role, "actions", []):
            if hasattr(action, "private_llm"):
                action.private_llm = None

    company.invest(investment)

    # ── Review gate: pause pipeline after key agents for user feedback ──
    review_queue: asyncio.Queue = asyncio.Queue()
    # Artifact types that trigger a review pause
    REVIEW_TRIGGERS = {"WritePRD", "WriteDesign"}

    # ── Shared state for review gate ──────────────────────────────────
    review_pending_info = {}  # set by patched_publish, consumed by patched_react

    # ── Monkey-patch env.publish_message to stream to WS ─────────────
    original_publish = company.env.publish_message

    def patched_publish(message, peekable=True):
        content_preview = str(getattr(message, "content", ""))[:80]
        cause = _safe_str(getattr(message, "cause_by", ""))
        sent = _safe_str(getattr(message, "sent_from", ""))
        print(f"[PUBLISH] from={sent} cause={cause} content_preview={content_preview!r}")
        # Fire-and-forget WS send
        asyncio.ensure_future(_send_message_update(ws, message, project_id))
        # Check if this message should trigger a review pause
        cause_by = str(getattr(message, "cause_by", ""))
        for trigger in REVIEW_TRIGGERS:
            if trigger in cause_by:
                content_str = str(getattr(message, "content", ""))
                review_pending_info["pending"] = {
                    "agent_name": str(getattr(message, "sent_from", "unknown")),
                    "artifact_type": trigger,
                    "content": content_str[:10000],
                }
                break
        return original_publish(message, peekable)

    object.__setattr__(company.env, 'publish_message', patched_publish)

    # ── Patch EACH ROLE INSTANCE's _react (not the class) ─────────────
    from metagpt.roles.role import Role
    original_react = Role._react  # save the unpatched class method

    async def patched_react(self_role):
        role_name = self_role.name or self_role.profile
        role_profile = self_role.profile
        print(f"[PIPELINE] Agent starting: {role_name} ({role_profile})")
        try:
            await ws.send_json(
                {
                    "type": "agent_start",
                    "agent_name": role_name,
                    "agent_role": role_profile,
                }
            )
        except Exception as e:
            print(f"[PIPELINE] Failed to send agent_start: {e}")

        result = await original_react(self_role)

        # ── Block pipeline here if review is needed ──
        if "pending" in review_pending_info:
            pending = review_pending_info.pop("pending")
            await _request_review(
                ws, review_queue,
                agent_name=pending["agent_name"],
                artifact_type=pending["artifact_type"],
                content=pending["content"],
            )

        print(f"[PIPELINE] Agent done: {role_name} ({role_profile})")
        try:
            await ws.send_json(
                {
                    "type": "agent_done",
                    "agent_name": role_name,
                    "agent_role": role_profile,
                }
            )
        except Exception as e:
            print(f"[PIPELINE] Failed to send agent_done: {e}")
        return result

    # Patch each role INSTANCE, not the class — avoids global state issues
    for role in company.env.roles.values():
        # Create a bound async method that calls patched_react with the role
        async def _bound_react(self_role=role):
            return await patched_react(self_role)
        role._react = _bound_react

    # ── Background listener for user WS messages (review responses) ───
    async def _ws_listener():
        """Listen for incoming WS messages from the user during pipeline."""
        try:
            while True:
                raw = await ws.receive_text()
                data = json.loads(raw)
                if data.get("type") in ("approve", "modify", "reject"):
                    await review_queue.put(data)
        except (WebSocketDisconnect, Exception):
            # Connection closed or error — unblock any waiting review
            await review_queue.put({"type": "approve"})

    listener_task = asyncio.create_task(_ws_listener())

    try:
        print(f"[PIPELINE] Starting pipeline for project {project_id}: {prompt}")
        await ws.send_json({"type": "pipeline_start", "prompt": prompt})
        await company.run(n_round=n_round, idea=prompt)
        print(f"[PIPELINE] Pipeline completed for project {project_id}")
    finally:
        listener_task.cancel()
        object.__setattr__(company.env, 'publish_message', original_publish)

    # Return workspace path
    project_path = ctx.kwargs.get("project_path", "")
    if not project_path:
        project_path = _find_workspace(project_id)
    return str(project_path)


async def _request_review(ws: WebSocket, review_queue: asyncio.Queue, agent_name: str, artifact_type: str, content: str):
    """Send a review request to the user and wait for their response.
    Blocks the pipeline until user approves, modifies, or rejects.
    Auto-approves after 5 minutes timeout."""
    try:
        await ws.send_json({
            "type": "review_request",
            "agent_name": agent_name,
            "artifact_type": artifact_type,
            "content": content,
        })
    except Exception:
        return  # WS closed, auto-approve

    try:
        response = await asyncio.wait_for(review_queue.get(), timeout=300)  # 5 min timeout
    except asyncio.TimeoutError:
        try:
            await ws.send_json({"type": "review_auto_approved", "artifact_type": artifact_type})
        except Exception:
            pass
        return

    action = response.get("type", "approve")
    if action == "reject":
        raise Exception(f"User rejected {artifact_type} artifact. Pipeline aborted.")
    elif action == "modify":
        # User provided modified content — log it but the pipeline continues
        # with the already-published artifact (modifications noted for next iteration)
        try:
            await ws.send_json({
                "type": "review_accepted",
                "artifact_type": artifact_type,
                "modified": True,
            })
        except Exception:
            pass
    # "approve" — just continue


def _safe_str(val) -> str:
    """Convert any value to a JSON-safe string. Handles sets, lists, enums, etc."""
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, (set, frozenset)):
        return ", ".join(str(v) for v in val)
    if isinstance(val, (list, tuple)):
        return ", ".join(str(v) for v in val)
    return str(val)


def _friendly_agent_name(raw_name: str) -> str:
    """Convert 'metagpt.roles.architect.Architect' to 'Bob (Architect)' etc."""
    _name_map = {
        "ProductManager": "Alice",
        "Architect": "Bob",
        "ProjectManager": "Eve",
        "Engineer": "Alex",
        "QaEngineer": "Edward",
    }
    # Extract class name from dotted path
    class_name = raw_name.rsplit(".", 1)[-1] if "." in raw_name else raw_name
    friendly = _name_map.get(class_name, class_name)
    if friendly != class_name:
        return f"{friendly} ({class_name})"
    return raw_name


def _friendly_action_name(raw_cause: str) -> str:
    """Convert 'metagpt.actions.write_prd.WritePRD' to 'WritePRD'."""
    if "." in raw_cause:
        return raw_cause.rsplit(".", 1)[-1]
    return raw_cause


async def _send_message_update(ws: WebSocket, message, project_id: str = ""):
    """Send a MetaGPT Message as a JSON event over WebSocket and persist to DB."""
    try:
        content = str(message.content) if hasattr(message, "content") else str(message)
        sent_from_raw = _safe_str(getattr(message, "sent_from", ""))
        sent_from = _friendly_agent_name(sent_from_raw)
        cause_by = _friendly_action_name(_safe_str(getattr(message, "cause_by", "")))
        role_val = _safe_str(getattr(message, "role", ""))
        send_to = _safe_str(getattr(message, "send_to", ""))
        data = {
            "type": "message",
            "content": content[:10000],  # limit content size
            "role": role_val,
            "cause_by": cause_by,
            "sent_from": sent_from,
            "send_to": send_to,
        }
        print(f"[WS] Sending message from {sent_from} (cause: {cause_by}), content length: {len(content)}")
        await ws.send_json(data)

        # Persist to Supabase
        if project_id and content:
            try:
                db.save_message(project_id, "agent", content[:5000], agent_name=sent_from)
            except Exception:
                pass
    except Exception as e:
        print(f"[WS] Failed to send message: {e}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
