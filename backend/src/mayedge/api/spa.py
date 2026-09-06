"""Serve the built SPA from FastAPI when WEB_ROOT is set (Docker)."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from mayedge.config import settings

logger = logging.getLogger(__name__)


def safe_file(root: Path, full_path: str) -> Path | None:
    if not full_path:
        return None
    candidate = (root / full_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def mount_spa(app: FastAPI) -> None:
    raw = (settings.web_root or "").strip()
    if not raw:
        return
    root = Path(raw).expanduser()
    index = root / "index.html"
    if not index.is_file():
        logger.warning("WEB_ROOT=%s has no index.html; SPA not mounted", root)
        return
    root = root.resolve()
    index = root / "index.html"

    @app.get("/{full_path:path}")
    async def spa(full_path: str) -> FileResponse:
        found = safe_file(root, full_path)
        if found is not None:
            return FileResponse(found)
        if full_path and ".." in Path(full_path).parts:
            raise HTTPException(404)
        return FileResponse(index)
