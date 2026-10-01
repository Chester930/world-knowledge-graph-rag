import importlib
import os
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

MODULE = "scripts.eval.diagnose_prompt_noise"
KEYS = ("WORKSPACE_DIR", "NEO4J_URI", "NEO4J_PASSWORD", "OLLAMA_BASE_URL")


class ImportHasNoEnvironSideEffectTest(unittest.TestCase):
    """匯入 `diagnose_prompt_noise` 不得修改 `os.environ`（報告189 D2；同 B1／C3 的汙染模式）。"""

    def _fresh_import(self):
        saved = sys.modules.pop(MODULE, None)
        try:
            return importlib.import_module(MODULE)
        finally:
            sys.modules.pop(MODULE, None)
            if saved is not None:
                sys.modules[MODULE] = saved

    def test_import_does_not_touch_environ(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            for k in KEYS:
                os.environ.pop(k, None)
            before = dict(os.environ)
            self._fresh_import()
            self.assertEqual({k: os.environ.get(k) for k in KEYS}, {k: None for k in KEYS})
            self.assertEqual(before, dict(os.environ))

    def test_apply_default_env_sets_missing_but_never_overrides(self):
        mod = self._fresh_import()
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            for k in KEYS:
                os.environ.pop(k, None)
            os.environ["NEO4J_URI"] = "bolt://example:1"
            mod.apply_default_env()
            self.assertEqual(os.environ["NEO4J_URI"], "bolt://example:1")  # 既有值不被覆蓋
            for k in KEYS:
                self.assertIn(k, os.environ)
            self.assertEqual(os.environ["OLLAMA_BASE_URL"], mod.DEFAULT_ENV["OLLAMA_BASE_URL"])


if __name__ == "__main__":
    unittest.main()
