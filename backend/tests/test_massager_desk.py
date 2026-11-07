"""The Massager on the desk: its band, its family name and its push label (phase 3)."""

from __future__ import annotations

import unittest

from mayedge.algos.massager.config import MASSAGER_COI_BASE, MASSAGER_COI_END
from mayedge.journal import family_of
from mayedge.lighter.coi import is_algo_client_order
from mayedge.push_text import _FAMILIES  # pyright: ignore[reportPrivateUsage]


class MassagerDeskTests(unittest.TestCase):
    def test_its_band_is_an_algo_band(self) -> None:
        self.assertTrue(is_algo_client_order(MASSAGER_COI_BASE))
        self.assertTrue(is_algo_client_order(MASSAGER_COI_END - 1))
        self.assertFalse(is_algo_client_order(MASSAGER_COI_END))

    def test_its_runs_are_named_massager(self) -> None:
        self.assertEqual(family_of("MS-0001"), "massager")
        self.assertEqual(_FAMILIES["massager"], "Massager")


if __name__ == "__main__":
    unittest.main()
