"""The JSON row guards check what isinstance checks, and fall back to empty."""

from __future__ import annotations

import unittest

from mayedge.rows import is_list, is_obj, items, obj


class RowsTests(unittest.TestCase):
    def test_guards_match_isinstance(self) -> None:
        for raw in ({}, {"a": 1}, [], [1], "x", None, 3, ()):
            self.assertEqual(is_obj(raw), isinstance(raw, dict))
            self.assertEqual(is_list(raw), isinstance(raw, list))

    def test_a_row_of_the_wrong_kind_reads_as_empty(self) -> None:
        row = {"a": 1}
        self.assertIs(obj(row), row)
        self.assertEqual(obj([1]), {})
        self.assertEqual(obj(None), {})
        rows = [1, 2]
        self.assertIs(items(rows), rows)
        self.assertEqual(items({"a": 1}), [])
        self.assertEqual(items("ab"), [])


if __name__ == "__main__":
    unittest.main()
