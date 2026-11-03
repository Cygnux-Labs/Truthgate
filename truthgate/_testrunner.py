"""Minimal test runner (no pytest needed). Usage: python _testrunner.py <tests_dir>

Prints one line per test and a final summary line:
    RESULT passed=<n> failed=<m>
"""
import importlib.util
import os
import sys
import traceback


def main(tests_dir: str) -> int:
    passed = failed = 0
    for fname in sorted(os.listdir(tests_dir)):
        if not (fname.startswith("test_") and fname.endswith(".py")):
            continue
        path = os.path.join(tests_dir, fname)
        spec = importlib.util.spec_from_file_location(fname[:-3], path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception:
            print(f"ERROR {fname}: could not import")
            print(traceback.format_exc(limit=2))
            failed += 1
            continue
        for name in sorted(dir(mod)):
            if not name.startswith("test_"):
                continue
            fn = getattr(mod, name)
            if not callable(fn):
                continue
            try:
                fn()
                print(f"PASS {fname}::{name}")
                passed += 1
            except AssertionError as e:
                print(f"FAIL {fname}::{name} AssertionError {e}")
                failed += 1
            except Exception as e:  # noqa: BLE001
                print(f"FAIL {fname}::{name} {type(e).__name__}: {e}")
                failed += 1
    print(f"RESULT passed={passed} failed={failed}")
    return 0 if failed == 0 and passed > 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
