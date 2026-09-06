from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient

from mayedge.api.app import create_app
from mayedge.api.spa import safe_file
from mayedge.config import settings


class SpaMountTests(unittest.IsolatedAsyncioTestCase):
    async def test_serves_index_and_assets(self) -> None:
        with TemporaryDirectory() as td:
            base = Path(td)
            root = base / "web"
            root.mkdir()
            (root / "index.html").write_text("<html>desk</html>", encoding="utf-8")
            (root / "assets").mkdir()
            (root / "assets" / "app.js").write_text("ok", encoding="utf-8")
            (base / "secret.txt").write_text("nope", encoding="utf-8")
            with patch.object(settings, "web_root", str(root)):
                app = create_app()
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                home = await client.get("/")
                nested = await client.get("/some/client/route")
                asset = await client.get("/assets/app.js")
            self.assertEqual(home.status_code, 200)
            self.assertIn("desk", home.text)
            self.assertEqual(nested.status_code, 200)
            self.assertIn("desk", nested.text)
            self.assertEqual(asset.status_code, 200)
            self.assertEqual(asset.text, "ok")
            resolved = root.resolve()
            self.assertIsNone(safe_file(resolved, "../secret.txt"))
            self.assertEqual(safe_file(resolved, "assets/app.js"), resolved / "assets" / "app.js")

    async def test_skipped_when_unset(self) -> None:
        with patch.object(settings, "web_root", ""):
            app = create_app()
        paths = {getattr(r, "path", None) for r in app.router.routes}
        self.assertNotIn("/{full_path:path}", paths)
