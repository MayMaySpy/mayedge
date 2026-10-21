"""web/src/lib/api.gen.ts is what the API's schemas generate today."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import api_types


class ApiTypesTests(unittest.TestCase):
    def test_the_web_types_are_current(self) -> None:
        self.assertEqual(
            api_types.OUT.read_text(),
            api_types.generated(),
            "web/src/lib/api.gen.ts is stale: run `make api-types`",
        )

    def test_a_nullable_list_of_refs_reads_as_typescript(self) -> None:
        doc = {
            "components": {
                "schemas": {
                    "Row": {
                        "type": "object",
                        "required": ["a"],
                        "properties": {
                            "a": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                            "b": {"type": "array", "items": {"$ref": "#/components/schemas/X"}},
                            "c": {"enum": ["x", "y"]},
                        },
                    }
                }
            }
        }
        self.assertIn(
            'export interface Row {\n  a: string | null;\n  b?: X[];\n  c?: "x" | "y";\n}',
            api_types.render(doc),
        )


if __name__ == "__main__":
    unittest.main()
