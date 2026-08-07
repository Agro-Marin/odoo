import importlib
import inspect


def _probe(obj: object, label: str) -> str | None:
    try:
        inspect.signature(obj)
    except (NameError, AttributeError) as e:
        return f"{label}: {type(e).__name__}: {e}"
    except TypeError, ValueError:
        return None
    return None


def scan_module(modname: str) -> list[str]:
    try:
        m = importlib.import_module(modname)
    except Exception as e:
        return [f"{modname}: import-fail: {type(e).__name__}: {e}"]

    fails: list[str] = []
    for name in dir(m):
        if name.startswith("_"):
            continue
        obj = getattr(m, name)
        if getattr(obj, "__module__", None) != modname:
            continue
        if callable(obj):
            err = _probe(obj, f"{modname}.{name}")
            if err:
                fails.append(err)
        if inspect.isclass(obj):
            for mname, mval in vars(obj).items():
                if callable(mval) and not mname.startswith("__"):
                    err = _probe(mval, f"{modname}.{name}.{mname}")
                    if err:
                        fails.append(err)
    return fails


def scan_modules(modnames: list[str]) -> dict[str, list[str]]:
    return {m: fails for m in modnames if (fails := scan_module(m))}
