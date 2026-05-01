"""
Nexus AI — Docker container manager for live project previews.
Handles building and running preview containers for generated projects.
"""

import os
import shutil
import threading
import time
from pathlib import Path
from typing import Optional

import docker
from docker.errors import NotFound, APIError

from builders import detect_framework, get_dockerfile_content, get_start_command

# Port range for preview containers
PORT_START = 9000
PORT_END = 9100

# Auto-stop containers after this many seconds of idle time
IDLE_TIMEOUT = 1800  # 30 minutes

# Track active containers: project_id -> { container_id, port, framework, started_at }
_active: dict[str, dict] = {}
_lock = threading.Lock()


def _get_client() -> docker.DockerClient:
    return docker.from_env()


def _next_port() -> int:
    """Find the next available port in the range."""
    used = {info["port"] for info in _active.values()}
    for port in range(PORT_START, PORT_END):
        if port not in used:
            return port
    raise RuntimeError(f"No available ports in range {PORT_START}-{PORT_END}")


def _find_code_dir(ws_path: Path) -> Path:
    """
    MetaGPT nests source code inside a timestamp subdirectory.
    Find that directory, or return ws_path itself if code is at root.
    """
    # If src/ or package.json exists at root, code is here
    if (ws_path / "src").exists() or (ws_path / "package.json").exists():
        return ws_path
    # Look for a timestamp-named subdirectory containing src/
    for child in sorted(ws_path.iterdir()):
        if child.is_dir() and (child / "src").exists():
            return child
    # Look for any subdir with .jsx/.tsx files
    for child in sorted(ws_path.iterdir()):
        if child.is_dir() and child.name not in ("docs", "resources", "tests", "test_outputs"):
            if list(child.rglob("*.jsx")) or list(child.rglob("*.tsx")) or list(child.rglob("*.vue")):
                return child
    return ws_path


def _is_valid_npm_package(name: str) -> bool:
    """
    Return True only if the string looks like a real npm package name.
    Rejects: node: builtins, template literals, single chars, internal
    module names, and anything with special characters that npm wouldn't allow.
    """
    import re

    if not name:
        return False

    # Reject node: protocol built-ins (node:fs, node:path, etc.)
    if name.startswith("node:"):
        return False

    # Reject template literals / interpolations
    if "${" in name or name.startswith("$"):
        return False

    # Reject names that contain spaces, newlines, parens, or other non-npm chars
    if re.search(r'[\s\(\)\[\]\{\}\;\:\,\!\=\+\*\%\^\&\|\<\>\\]', name):
        return False

    # Reject single-character "package names" (u, b, q, A, T, etc.)
    if len(name) <= 1:
        return False

    # Reject names that look like Node.js core modules referenced without node: prefix
    _node_core = {
        "fs", "path", "os", "url", "http", "https", "stream", "crypto",
        "util", "events", "child_process", "buffer", "assert", "querystring",
        "zlib", "net", "tls", "dns", "readline", "repl", "module",
        "worker_threads", "perf_hooks", "async_hooks", "v8", "vm",
        "tty", "process", "timers",
    }
    if name in _node_core:
        return False

    # Reject names that are clearly not packages (placeholders, single words without hyphens
    # that look like internal helpers, etc.)
    _known_non_packages = {
        "foo", "bar", "baz", "hello", "world", "A", "T", "u", "b", "q",
        "someLibrary", "some-module", "moquire", "pnpapi",
    }
    if name in _known_non_packages:
        return False

    # Valid npm package names: lowercase letters, digits, hyphens, underscores, dots
    # Scoped packages start with @scope/name
    if name.startswith("@"):
        parts = name.split("/")
        if len(parts) < 2:
            return False
        scope_valid = re.fullmatch(r'@[a-z0-9\-_\.]+', parts[0])
        pkg_valid = re.fullmatch(r'[a-z0-9\-_\.]+', parts[1])
        return bool(scope_valid and pkg_valid)
    else:
        return bool(re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9\-_\.]*', name) and len(name) >= 2)


def _scan_npm_imports(code_dir: Path) -> set[str]:
    """
    Scan JS/JSX/TSX source files for npm package imports.
    Returns a set of top-level npm package names (e.g. '@mui/icons-material').
    Only returns names that pass the _is_valid_npm_package check.
    """
    import re
    npm_packages: set[str] = set()
    # Match: import ... from "pkg" / import ... from 'pkg'
    #    or: require("pkg") / require('pkg')
    import_re = re.compile(
        r'(?:import\s+.*?from\s+|require\s*\(\s*)["\']([^"\'\/\.][^"\']*)["\']',
    )
    for ext in ("*.js", "*.jsx", "*.tsx", "*.ts"):
        for src_file in code_dir.rglob(ext):
            try:
                text = src_file.read_text(errors="replace")
            except Exception:
                continue
            for match in import_re.finditer(text):
                pkg = match.group(1)
                # Extract top-level package name:
                #   @scope/pkg/sub  -> @scope/pkg
                #   pkg/sub         -> pkg
                if pkg.startswith("@"):
                    parts = pkg.split("/")
                    if len(parts) >= 2:
                        candidate = f"{parts[0]}/{parts[1]}"
                    else:
                        continue
                else:
                    candidate = pkg.split("/")[0]

                if _is_valid_npm_package(candidate):
                    npm_packages.add(candidate)

    return npm_packages


def _clean_metagpt_artifacts(code_dir: Path):
    """
    MetaGPT sometimes prepends filenames as markdown headers (e.g. '## src/index.css')
    to generated source files. Strip these so parsers/compilers don't choke.
    """
    import re
    for ext in ("*.css", "*.js", "*.jsx", "*.ts", "*.tsx", "*.json", "*.html"):
        for f in code_dir.rglob(ext):
            try:
                text = f.read_text(errors="replace")
                # Strip leading '## filename' or '# filename' lines
                if re.match(r'^#{1,3}\s+\S+', text):
                    cleaned = re.sub(r'^#{1,3}\s+\S+.*\n?', '', text, count=1)
                    if cleaned != text:
                        f.write_text(cleaned)
                        print(f"[SCAFFOLD] Stripped markdown header from {f.relative_to(code_dir)}")
            except Exception:
                continue


def _scaffold_react_project(code_dir: Path, ws_path: Path):
    """
    Generate missing scaffolding files for a React/Vite project.
    MetaGPT generates source code but not package.json, index.html, or vite.config.js.
    """
    # Clean MetaGPT artifacts (markdown headers in source files)
    _clean_metagpt_artifacts(code_dir)

    # Read requirements.txt from workspace root for dependencies
    deps = {}
    dev_deps = {}
    req_file = ws_path / "requirements.txt"
    if req_file.exists():
        for line in req_file.read_text().splitlines():
            pkg = line.strip()
            if not pkg:
                continue
            if pkg in ("vite", "@vitejs/plugin-react", "tailwindcss", "postcss", "autoprefixer"):
                dev_deps[pkg] = "latest"
            else:
                deps[pkg] = "latest"
    # Ensure react/react-dom are always present with compatible versions
    deps.setdefault("react", "^18.2.0")
    deps.setdefault("react-dom", "^18.2.0")
    dev_deps.setdefault("vite", "^5.0.0")
    dev_deps.setdefault("@vitejs/plugin-react", "^4.0.0")
    # Pin tailwind to v3 — MetaGPT generates v3-style @tailwind directives
    if "tailwindcss" in dev_deps:
        dev_deps["tailwindcss"] = "^3.4.0"
    if "tailwindcss" in deps:
        deps["tailwindcss"] = "^3.4.0"

    # Scan source files for npm imports that MetaGPT forgot to list
    scanned = _scan_npm_imports(code_dir)
    # Known dev-only packages
    _dev_only = {"vite", "@vitejs/plugin-react", "tailwindcss", "postcss", "autoprefixer",
                 "@types/react", "@types/react-dom", "typescript", "eslint"}
    # Combine deps for version lookup
    all_deps = {**deps, **dev_deps}
    for pkg_name in scanned:
        if pkg_name not in deps and pkg_name not in dev_deps:
            # Determine version: match sibling scope package if exists
            version = "latest"
            if pkg_name.startswith("@"):
                scope = pkg_name.split("/")[0]
                for existing_pkg, existing_ver in all_deps.items():
                    if existing_pkg.startswith(scope + "/") and existing_ver != "latest":
                        version = existing_ver
                        break
            if pkg_name in _dev_only:
                dev_deps[pkg_name] = version
            else:
                deps[pkg_name] = version
            print(f"[SCAFFOLD] Auto-detected missing npm package: {pkg_name}@{version}")

    import json

    # package.json
    if not (code_dir / "package.json").exists():
        pkg = {
            "name": "nexus-preview",
            "private": True,
            "version": "0.0.1",
            "type": "module",
            "scripts": {
                "dev": "vite --host 0.0.0.0 --port 3000",
                "start": "vite --host 0.0.0.0 --port 3000",
                "build": "vite build",
                "preview": "vite preview --host 0.0.0.0 --port 3000"
            },
            "dependencies": deps,
            "devDependencies": dev_deps,
        }
        (code_dir / "package.json").write_text(json.dumps(pkg, indent=2))
    else:
        # Merge scanned deps + fix scripts in existing package.json
        try:
            existing = json.loads((code_dir / "package.json").read_text())
            existing_deps = existing.get("dependencies", {})
            existing_dev = existing.get("devDependencies", {})
            existing_scripts = existing.get("scripts", {})
            changed = False

            # Add missing npm packages detected from source imports
            all_existing = {**existing_deps, **existing_dev}
            for pkg_name in scanned:
                if pkg_name not in existing_deps and pkg_name not in existing_dev:
                    # Match version of sibling scoped packages
                    version = "latest"
                    if pkg_name.startswith("@"):
                        scope = pkg_name.split("/")[0]
                        for ep, ev in all_existing.items():
                            if ep.startswith(scope + "/") and ev != "latest":
                                version = ev
                                break
                    if pkg_name in _dev_only:
                        existing_dev[pkg_name] = version
                    else:
                        existing_deps[pkg_name] = version
                    changed = True
                    print(f"[SCAFFOLD] Patching existing package.json: +{pkg_name}@{version}")

            # Ensure scripts use --host 0.0.0.0 for Docker container access
            if "dev" in existing_scripts and "--host" not in existing_scripts["dev"]:
                existing_scripts["dev"] = "vite --host 0.0.0.0 --port 3000"
                changed = True
            if "start" not in existing_scripts:
                existing_scripts["start"] = "vite --host 0.0.0.0 --port 3000"
                changed = True

            if changed:
                existing["dependencies"] = existing_deps
                existing["devDependencies"] = existing_dev
                existing["scripts"] = existing_scripts
                (code_dir / "package.json").write_text(json.dumps(existing, indent=2))
        except Exception as e:
            print(f"[SCAFFOLD] Failed to patch package.json: {e}")

    # index.html
    if not (code_dir / "index.html").exists():
        # Find main entry point
        entry = "src/main.jsx"
        for candidate in ["src/main.jsx", "src/main.tsx", "src/index.jsx", "src/index.tsx"]:
            if (code_dir / candidate).exists():
                entry = candidate
                break
        (code_dir / "index.html").write_text(f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Preview</title>
</head>
<body>
  <div id="root"></div>
  <script type="module" src="/{entry}"></script>
</body>
</html>
""")

    # vite.config.js
    if not (code_dir / "vite.config.js").exists() and not (code_dir / "vite.config.ts").exists():
        (code_dir / "vite.config.js").write_text("""import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 3000,
  },
})
""")

    # tailwind.config.js (if tailwindcss is a dep)
    if "tailwindcss" in dev_deps or "tailwindcss" in deps:
        if not (code_dir / "tailwind.config.js").exists():
            (code_dir / "tailwind.config.js").write_text("""/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: { extend: {} },
  plugins: [],
}
""")
        if not (code_dir / "postcss.config.js").exists():
            (code_dir / "postcss.config.js").write_text("""export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
""")
        # Ensure CSS file has tailwind directives
        css_files = list(code_dir.rglob("*.css"))
        if css_files:
            css_content = css_files[0].read_text()
            if "@tailwind" not in css_content:
                css_files[0].write_text(f"@tailwind base;\n@tailwind components;\n@tailwind utilities;\n\n{css_content}")


def start_preview(project_id: str, workspace_path: str) -> dict:
    """
    Build and start a Docker container for the project.
    Returns { port, framework, container_id, status }.
    """
    client = _get_client()
    ws_path = Path(workspace_path)

    if not ws_path.exists():
        return {"status": "error", "message": "Workspace not found"}

    # Stop existing container for this project
    stop_preview(project_id)

    # Detect framework
    framework = detect_framework(ws_path)
    print(f"[CONTAINER] Detected framework: {framework} for {ws_path}")

    # Find the actual code directory (MetaGPT nests code in a timestamp subdir)
    code_dir = _find_code_dir(ws_path)
    print(f"[CONTAINER] Code directory: {code_dir}")

    # Scaffold missing files for JS frameworks
    if framework in ("react", "vue"):
        _scaffold_react_project(code_dir, ws_path)

    port = _next_port()

    # Write Dockerfile into the code directory (where package.json lives)
    dockerfile_content = get_dockerfile_content(framework)
    dockerfile_path = code_dir / "Dockerfile"
    dockerfile_path.write_text(dockerfile_content)

    # Also write .dockerignore
    dockerignore_path = code_dir / ".dockerignore"
    dockerignore_path.write_text("node_modules\n.git\n__pycache__\n*.pyc\n.env\n")

    # Build image from the code directory (where Dockerfile and package.json live)
    image_tag = f"nexus-preview-{project_id}:latest"
    print(f"[CONTAINER] Building Docker image from {code_dir}")
    try:
        image, build_logs = client.images.build(
            path=str(code_dir),
            tag=image_tag,
            rm=True,
            forcerm=True,
        )
        for log_line in build_logs:
            if 'stream' in log_line:
                print(f"[DOCKER] {log_line['stream'].rstrip()}")
            elif 'error' in log_line:
                print(f"[DOCKER ERROR] {log_line['error'].rstrip()}")
    except Exception as e:
        print(f"[CONTAINER] Build failed: {e}")
        return {"status": "error", "message": f"Build failed: {e}"}

    # Run container
    internal_port = _get_internal_port(framework)
    try:
        container = client.containers.run(
            image_tag,
            detach=True,
            ports={f"{internal_port}/tcp": port},
            name=f"nexus-preview-{project_id}",
            remove=False,
            environment={"PORT": str(internal_port)},
        )
    except Exception as e:
        return {"status": "error", "message": f"Container start failed: {e}"}

    with _lock:
        _active[project_id] = {
            "container_id": container.id,
            "port": port,
            "framework": framework,
            "started_at": time.time(),
            "image_tag": image_tag,
        }

    # Clean up Dockerfile from workspace
    dockerfile_path.unlink(missing_ok=True)
    dockerignore_path.unlink(missing_ok=True)

    return {
        "status": "running",
        "port": port,
        "framework": framework,
        "container_id": container.short_id,
        "url": f"http://localhost:{port}",
        "proxy_url": f"/api/projects/{project_id}/container/view/",
    }


def stop_preview(project_id: str) -> dict:
    """Stop and remove the container for a project."""
    client = _get_client()
    with _lock:
        info = _active.pop(project_id, None)
    if not info:
        # Also try to find and remove by name
        try:
            c = client.containers.get(f"nexus-preview-{project_id}")
            c.stop(timeout=5)
            c.remove(force=True)
        except (NotFound, APIError):
            pass
        return {"status": "stopped"}

    try:
        container = client.containers.get(info["container_id"])
        container.stop(timeout=5)
        container.remove(force=True)
    except (NotFound, APIError):
        pass

    # Remove image
    try:
        client.images.remove(info.get("image_tag", ""), force=True)
    except Exception:
        pass

    return {"status": "stopped"}


def get_preview_status(project_id: str) -> dict:
    """Get the current status of a project's preview container."""
    with _lock:
        info = _active.get(project_id)
    if not info:
        return {"status": "stopped"}

    client = _get_client()
    try:
        container = client.containers.get(info["container_id"])
        return {
            "status": container.status,  # running, exited, etc.
            "port": info["port"],
            "framework": info["framework"],
            "url": f"http://localhost:{info['port']}",
            "proxy_url": f"/api/projects/{project_id}/container/view/",
            "container_id": container.short_id,
        }
    except NotFound:
        with _lock:
            _active.pop(project_id, None)
        return {"status": "stopped"}


def get_container_logs(project_id: str, tail: int = 100) -> str:
    """Get recent logs from a project's preview container."""
    with _lock:
        info = _active.get(project_id)
    if not info:
        return ""

    client = _get_client()
    try:
        container = client.containers.get(info["container_id"])
        return container.logs(tail=tail).decode("utf-8", errors="replace")
    except (NotFound, APIError):
        return ""


def cleanup_idle():
    """Stop containers that have been running longer than IDLE_TIMEOUT."""
    now = time.time()
    to_stop = []
    with _lock:
        for pid, info in _active.items():
            if now - info["started_at"] > IDLE_TIMEOUT:
                to_stop.append(pid)
    for pid in to_stop:
        stop_preview(pid)


def cleanup_all():
    """Stop all preview containers."""
    with _lock:
        pids = list(_active.keys())
    for pid in pids:
        stop_preview(pid)


def _get_internal_port(framework: str) -> int:
    """Get the internal port the app runs on inside the container."""
    port_map = {
        "react": 3000,
        "vue": 5173,
        "nextjs": 3000,
        "python": 8080,
        "flask": 5000,
        "django": 8000,
        "fastapi": 8000,
        "flutter": 80,
        "static": 80,
    }
    return port_map.get(framework, 80)
