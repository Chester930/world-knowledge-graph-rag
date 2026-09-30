import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.analysis.check_node_cards import main, run


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


CARD_OK = """# 假節點
| 葉節點 | 現在位置 | 狀態 |
| --- | --- | --- |
| a | `pkg/node_a/mod.py::moved_fn`（`:1`）、`other_fn`（`:5`） | 已搬移 |
| b | `legacy/old.py::stay_fn` | 仍在原處 |
"""


class CheckNodeCardsTest(unittest.TestCase):
    def _fixture(self, root: Path) -> None:
        _write(root, "pkg/node_a/NODE.md", CARD_OK)
        _write(root, "pkg/node_a/mod.py", "def moved_fn():\n    pass\n\n\ndef other_fn():\n    pass\n")
        _write(root, "legacy/old.py", "def stay_fn():\n    pass\n")

    def test_clean_fixture_has_no_warnings(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._fixture(root)
            self.assertEqual(run(root), [])
            self.assertEqual(main(["--root", d, "--strict"]), 0)

    def test_detects_missing_function(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._fixture(root)
            _write(root, "legacy/old.py", "def something_else():\n    pass\n")
            warnings = run(root)
            self.assertTrue(any("找不到 stay_fn" in w for w in warnings), warnings)

    def test_detects_inherited_bare_name_missing(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._fixture(root)
            _write(root, "pkg/node_a/mod.py", "def moved_fn():\n    pass\n")
            warnings = run(root)
            self.assertTrue(any("找不到 other_fn" in w for w in warnings), warnings)

    def test_detects_cross_node_import(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._fixture(root)
            _write(root, "pkg/node_b/NODE.md", "# 假節點B\n")
            _write(root, "pkg/node_b/inner.py", "def helper():\n    pass\n")
            _write(root, "pkg/node_a/mod.py", "from pkg.node_b.inner import helper\n\n\ndef moved_fn():\n    pass\n\n\ndef other_fn():\n    pass\n")
            warnings = run(root)
            self.assertTrue(any("import 了其他節點資料夾" in w and "pkg.node_b.inner" in w for w in warnings), warnings)

    def test_detects_claimed_moved_but_still_outside(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._fixture(root)
            _write(
                root,
                "pkg/node_a/NODE.md",
                CARD_OK.replace("`pkg/node_a/mod.py::moved_fn`（`:1`）、`other_fn`（`:5`） | 已搬移", "`legacy/old.py::stay_fn` | 已搬移"),
            )
            warnings = run(root)
            self.assertTrue(any("標「已搬移」但 legacy/old.py" in w for w in warnings), warnings)

    def test_detects_claimed_staying_but_actually_inside(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._fixture(root)
            _write(
                root,
                "pkg/node_a/NODE.md",
                CARD_OK.replace("`legacy/old.py::stay_fn` | 仍在原處", "`pkg/node_a/mod.py::moved_fn` | 仍在原處"),
            )
            warnings = run(root)
            self.assertTrue(any("標「仍在原處」但 pkg/node_a/mod.py" in w for w in warnings), warnings)

    def test_default_mode_exit_zero_strict_nonzero(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._fixture(root)
            _write(root, "legacy/old.py", "def something_else():\n    pass\n")
            self.assertEqual(main(["--root", d]), 0)
            self.assertEqual(main(["--root", d, "--strict"]), 1)

    def test_real_cards_have_no_warnings(self):
        warnings = run(REPO)
        self.assertEqual(warnings, [], warnings)


if __name__ == "__main__":
    unittest.main()
