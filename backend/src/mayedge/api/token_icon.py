"""Same-origin proxy for Lighter token PNGs.

Firefox OpaqueResponseBlocking logs when a cross-origin `<img>` gets a
non-image (403/404 text). Fetching here and returning 404 keeps the desk
quiet and still falls back to the letter mark.
"""

from __future__ import annotations

import re
import time

import httpx
from fastapi import HTTPException
from fastapi.responses import Response

_SLUG = re.compile(r"^[a-z0-9]{1,32}$")
_TTL_HIT = 6 * 3600
_TTL_MISS = 15 * 60
_CDN = "https://assets.lighter.xyz/fe/token/{slug}.png"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://app.lighter.xyz/",
    "Accept": "image/png,image/webp,image/*;q=0.8,*/*;q=0.5",
}

# slug -> (expires_at, body or None, content-type)
_cache: dict[str, tuple[float, bytes | None, str]] = {}


async def token_icon_response(slug: str) -> Response:
    key = slug.lower()
    if not _SLUG.fullmatch(key):
        raise HTTPException(404)
    now = time.monotonic()
    cached = _cache.get(key)
    if cached and cached[0] > now:
        body, ctype = cached[1], cached[2]
        if body is None:
            raise HTTPException(404)
        return Response(
            content=body,
            media_type=ctype,
            headers={"Cache-Control": "public, max-age=3600"},
        )
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(_CDN.format(slug=key), headers=_HEADERS)
    except httpx.HTTPError as e:
        _cache[key] = (now + _TTL_MISS, None, "")
        raise HTTPException(404) from e
    ctype = (resp.headers.get("content-type") or "").split(";", 1)[0].strip()
    if resp.status_code != 200 or not ctype.startswith("image/") or not resp.content:
        _cache[key] = (now + _TTL_MISS, None, "")
        raise HTTPException(404)
    _cache[key] = (now + _TTL_HIT, resp.content, ctype)
    return Response(
        content=resp.content,
        media_type=ctype,
        headers={"Cache-Control": "public, max-age=3600"},
    )
