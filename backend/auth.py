"""Nexus AI — Authentication middleware using Supabase JWT.
Verifies the Bearer token from the Authorization header and injects user_id.
Supports both ES256 (newer Supabase projects) and HS256 (legacy).
"""

import json
import os
import ssl
import urllib.request
from typing import Optional

from fastapi import Request, HTTPException, WebSocket
from jose import jwt, JWTError, jwk

# ── Cached JWKS key ──────────────────────────────────────────────────
_cached_jwks: dict | None = None


def _get_supabase_url() -> str:
    return os.getenv("SUPABASE_URL", "")


def _get_jwt_secret() -> str:
    return os.getenv("SUPABASE_JWT_SECRET", "")


def _fetch_jwks() -> dict:
    """Fetch the JWKS public keys from Supabase for ES256 verification."""
    global _cached_jwks
    if _cached_jwks:
        return _cached_jwks
    url = f"{_get_supabase_url()}/auth/v1/.well-known/jwks.json"
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            _cached_jwks = json.loads(resp.read())
            return _cached_jwks
    except Exception as e:
        print(f"[AUTH] Failed to fetch JWKS from {url}: {e}")
        return {"keys": []}


def _get_es256_key(kid: str = None):
    """Get the ES256 public key from JWKS for token verification."""
    jwks = _fetch_jwks()
    for key_data in jwks.get("keys", []):
        if key_data.get("alg") == "ES256":
            if kid and key_data.get("kid") != kid:
                continue
            return jwk.construct(key_data, algorithm="ES256")
    return None


def _decode_token(token: str) -> dict:
    """Decode and verify a Supabase JWT. Supports ES256 and HS256."""
    try:
        header = jwt.get_unverified_header(token)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Malformed token: {e}")

    alg = header.get("alg", "")

    # ES256 — newer Supabase projects use asymmetric signing
    if alg == "ES256":
        kid = header.get("kid")
        key = _get_es256_key(kid)
        if not key:
            raise HTTPException(status_code=401, detail="ES256 public key not found in JWKS")
        try:
            payload = jwt.decode(
                token, key,
                algorithms=["ES256"],
                audience="authenticated",
            )
            return payload
        except JWTError as e:
            raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

    # HS256/HS384/HS512 — legacy Supabase projects
    secret = _get_jwt_secret()
    if not secret:
        raise HTTPException(status_code=401, detail="SUPABASE_JWT_SECRET not configured")
    try:
        payload = jwt.decode(
            token, secret,
            algorithms=["HS256", "HS384", "HS512"],
            audience="authenticated",
        )
        return payload
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


def get_user_id_from_request(request: Request) -> str:
    """Extract and verify user_id from the Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = auth_header[7:]
    payload = _decode_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing 'sub' claim")
    return user_id


def get_user_id_from_ws(ws: WebSocket) -> str:
    """Extract user_id from WebSocket query params (?token=xxx)."""
    token = ws.query_params.get("token", "")
    if not token:
        raise HTTPException(status_code=401, detail="Missing token query parameter")
    payload = _decode_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing 'sub' claim")
    return user_id


def get_optional_user_id(request: Request) -> Optional[str]:
    """Try to get user_id but return None if no auth header present (for public endpoints)."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    try:
        token = auth_header[7:]
        payload = _decode_token(token)
        return payload.get("sub")
    except Exception:
        return None
