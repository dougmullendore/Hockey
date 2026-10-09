"""Run the tests without pytest installed:  python tests/run_local.py"""
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tests.test_site as T  # noqa: E402

failed = 0
for name in [n for n in dir(T) if n.startswith("test_")]:
    try:
        getattr(T, name)()
        print("PASS", name)
    except Exception:
        failed += 1
        print("FAIL", name)
        traceback.print_exc()
sys.exit(1 if failed else 0)
