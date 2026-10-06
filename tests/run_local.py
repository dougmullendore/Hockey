"""Run the tests without pytest installed:  python tests/run_local.py"""
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tests.test_pipeline as T  # noqa: E402


class Monkey:
    def __init__(self):
        self.undo = []

    def setattr(self, obj, name, value):
        self.undo.append((setattr, obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def setitem(self, d, key, value):
        self.undo.append((d.__setitem__, key, d[key]))
        d[key] = value

    def restore(self):
        for fn, *args in reversed(self.undo):
            fn(*args)


class Factory:
    def mktemp(self, name):
        return Path(tempfile.mkdtemp(prefix=name))


data = getattr(T.data_dir, "__wrapped__", T.data_dir)(Factory())
failed = 0
for name in [n for n in dir(T) if n.startswith("test_")]:
    fn, mp = getattr(T, name), Monkey()
    args = fn.__code__.co_varnames[:fn.__code__.co_argcount]
    try:
        fn(**{a: {"data_dir": data, "monkeypatch": mp}[a] for a in args})
        print("PASS", name)
    except Exception:
        failed += 1
        print("FAIL", name)
        traceback.print_exc()
    finally:
        mp.restore()
sys.exit(1 if failed else 0)
