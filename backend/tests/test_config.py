from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from mayedge.config import Settings

EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"


class EnvExampleTests(unittest.TestCase):
    def test_the_shipped_example_boots_with_trading_off(self) -> None:
        with TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text(EXAMPLE.read_text())
            clean = {k: v for k, v in os.environ.items() if not k.upper().startswith("LIGHTER_")}
            with patch.dict(os.environ, clean, clear=True):
                got = Settings(_env_file=str(env))  # pyright: ignore[reportCallIssue]
        self.assertIsNone(got.lighter_account_index)
        self.assertFalse(got.trading_enabled)
        self.assertEqual(got.max_order_notional, 50_000.0)
