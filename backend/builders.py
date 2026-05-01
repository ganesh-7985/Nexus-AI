"""
Nexus AI — Framework detection and Dockerfile generation.
Detects the framework from generated project files and produces
appropriate Dockerfiles for live preview containers.
"""

import json
from pathlib import Path


# Known npm packages that appear in MetaGPT requirements.txt
_NPM_PACKAGES = {
    "react", "react-dom", "vue", "next", "vite", "svelte",
    "tailwindcss", "postcss", "autoprefixer", "webpack",
    "@mui/material", "@emotion/react", "@emotion/styled",
    "@vitejs/plugin-react", "typescript", "axios", "express",
}


def detect_framework(workspace: Path) -> str:
    """
    Detect the framework/language of a generated project.
    Returns one of: react, vue, nextjs, python, flask, django, fastapi, flutter, static
    """
    # 1) Check for package.json at root or in subdirectories
    for pkg_json in [workspace / "package.json"] + list(workspace.rglob("package.json")):
        if pkg_json.exists():
            try:
                pkg = json.loads(pkg_json.read_text())
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                if "next" in deps:
                    return "nextjs"
                if "vue" in deps:
                    return "vue"
                if "react" in deps:
                    return "react"
                return "react"  # generic node project
            except Exception:
                pass

    # 2) Check for JS/JSX/TSX/Vue source files (MetaGPT often generates these without package.json)
    jsx_files = list(workspace.rglob("*.jsx")) + list(workspace.rglob("*.tsx"))
    vue_files = list(workspace.rglob("*.vue"))
    if vue_files:
        return "vue"
    if jsx_files:
        return "react"

    # 3) Check requirements.txt — distinguish npm vs pip
    requirements = workspace / "requirements.txt"
    pipfile = workspace / "Pipfile"
    pyproject = workspace / "pyproject.toml"

    if requirements.exists():
        req_text = requirements.read_text().strip().lower()
        req_lines = {line.strip() for line in req_text.splitlines() if line.strip()}
        # If requirements.txt contains known npm packages, it's a JS project
        if req_lines & {p.lower() for p in _NPM_PACKAGES}:
            if "next" in req_lines:
                return "nextjs"
            if "vue" in req_lines:
                return "vue"
            return "react"
        # Otherwise treat as Python
        if "django" in req_text:
            return "django"
        if "flask" in req_text:
            return "flask"
        if "fastapi" in req_text:
            return "fastapi"
        return "python"

    if pipfile.exists() or pyproject.exists():
        return "python"

    # 4) Check for Python source files
    py_files = list(workspace.rglob("*.py"))
    if py_files:
        for py_file in py_files[:20]:
            try:
                content = py_file.read_text()[:2000]
                if "from fastapi" in content or "import fastapi" in content:
                    return "fastapi"
                if "from flask" in content or "import flask" in content:
                    return "flask"
                if "from django" in content or "import django" in content:
                    return "django"
            except Exception:
                continue
        return "python"

    # 5) Flutter detection
    pubspec = workspace / "pubspec.yaml"
    if pubspec.exists():
        return "flutter"

    # 6) Static HTML detection
    html_files = list(workspace.glob("*.html")) + list(workspace.rglob("*.html"))
    if html_files:
        return "static"

    return "static"


def get_dockerfile_content(framework: str) -> str:
    """Generate a Dockerfile for the given framework."""
    generators = {
        "react": _dockerfile_react,
        "vue": _dockerfile_vue,
        "nextjs": _dockerfile_nextjs,
        "python": _dockerfile_python,
        "flask": _dockerfile_flask,
        "django": _dockerfile_django,
        "fastapi": _dockerfile_fastapi,
        "flutter": _dockerfile_flutter,
        "static": _dockerfile_static,
    }
    gen = generators.get(framework, _dockerfile_static)
    return gen()


def get_start_command(framework: str) -> str:
    """Get the command to start the app inside the container."""
    commands = {
        "react": "npm start",
        "vue": "npm run dev -- --host 0.0.0.0",
        "nextjs": "npm run dev",
        "python": "python main.py",
        "flask": "python app.py",
        "django": "python manage.py runserver 0.0.0.0:8000",
        "fastapi": "uvicorn main:app --host 0.0.0.0 --port 8000",
        "flutter": "nginx -g 'daemon off;'",
        "static": "nginx -g 'daemon off;'",
    }
    return commands.get(framework, "nginx -g 'daemon off;'")


def get_framework_display_name(framework: str) -> str:
    """Human-readable framework name."""
    names = {
        "react": "React",
        "vue": "Vue.js",
        "nextjs": "Next.js",
        "python": "Python",
        "flask": "Flask",
        "django": "Django",
        "fastapi": "FastAPI",
        "flutter": "Flutter",
        "static": "Static HTML",
    }
    return names.get(framework, framework.title())


# ── Dockerfile generators ───────────────────────────────────────────

def _dockerfile_react() -> str:
    return """FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install || npm install --legacy-peer-deps || true
COPY . .
EXPOSE 3000
ENV HOST=0.0.0.0
CMD ["sh", "-c", "npx vite --host 0.0.0.0 --port 3000 2>&1 || npm run dev -- --host 0.0.0.0 --port 3000 2>&1 || npm start 2>&1 || npx serve -s . -l 3000"]
"""


def _dockerfile_vue() -> str:
    return """FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install 2>/dev/null || true
COPY . .
EXPOSE 5173
CMD ["sh", "-c", "npm run dev -- --host 0.0.0.0 2>/dev/null || npx vite --host 0.0.0.0"]
"""


def _dockerfile_nextjs() -> str:
    return """FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install 2>/dev/null || true
COPY . .
EXPOSE 3000
CMD ["sh", "-c", "npm run dev 2>/dev/null || npx next dev"]
"""


def _dockerfile_python() -> str:
    return """FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt* ./
RUN pip install --no-cache-dir -r requirements.txt 2>/dev/null || true
COPY . .
EXPOSE 8080
CMD ["python", "main.py"]
"""


def _dockerfile_flask() -> str:
    return """FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt* ./
RUN pip install --no-cache-dir -r requirements.txt 2>/dev/null || pip install flask || true
COPY . .
EXPOSE 5000
ENV FLASK_APP=app.py
ENV FLASK_RUN_HOST=0.0.0.0
CMD ["sh", "-c", "python app.py 2>/dev/null || flask run --host=0.0.0.0"]
"""


def _dockerfile_django() -> str:
    return """FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt* ./
RUN pip install --no-cache-dir -r requirements.txt 2>/dev/null || pip install django || true
COPY . .
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
"""


def _dockerfile_fastapi() -> str:
    return """FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt* ./
RUN pip install --no-cache-dir -r requirements.txt 2>/dev/null || pip install fastapi uvicorn || true
COPY . .
EXPOSE 8000
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 8000 2>/dev/null || python main.py"]
"""


def _dockerfile_flutter() -> str:
    return """FROM dart:stable AS build
RUN apt-get update && apt-get install -y git unzip
RUN git clone https://github.com/flutter/flutter.git /flutter --branch stable --depth 1
ENV PATH="/flutter/bin:/flutter/bin/cache/dart-sdk/bin:${PATH}"
RUN flutter config --no-analytics && flutter precache --web
WORKDIR /app
COPY . .
RUN flutter pub get && flutter build web

FROM nginx:alpine
COPY --from=build /app/build/web /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
"""


def _dockerfile_static() -> str:
    return """FROM nginx:alpine
COPY . /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
"""
