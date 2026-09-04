__all__ = [
    "JSON_SCRIPTSAFE_MAPPER",
    "ScriptSafe",
    "ScriptSafeJSON",
    "scriptsafe",
]

import json as json_
import re
from typing import Any

import markupsafe

JSON_SCRIPTSAFE_MAPPER: dict[str, str] = {
    "&": r"\u0026",
    "<": r"\u003c",
    ">": r"\u003e",
    "\u2028": r"\u2028",
    "\u2029": r"\u2029",
}


_SCRIPTSAFE_RE = re.compile(r"[<>&\u2028\u2029]")


class ScriptSafe(str):
    """A ``str`` whose plain form is valid, unescaped JSON. It is safe to
    embed in an HTML ``<script>`` context only through ``__html__()``
    (e.g. via a QWeb ``t-esc``/``Markup`` rendering path) -- treating an
    instance as a plain string bypasses the escaping entirely.
    """

    __slots__ = ()

    def __html__(self) -> markupsafe.Markup:
        return markupsafe.Markup(
            _SCRIPTSAFE_RE.sub(lambda m: JSON_SCRIPTSAFE_MAPPER[m[0]], self)
        )


class ScriptSafeJSON:
    """``json``-like ``loads``/``dumps`` where ``dumps`` returns a
    :class:`ScriptSafe`. Despite the name, ``dumps()``'s plain ``str`` form
    is intentionally unescaped valid JSON (pinned by
    ``test_dumps_raw_str_is_valid_unescaped_json``) -- only rendering it via
    ``__html__()`` makes it script-safe.
    """

    def loads(self, *args: Any, **kwargs: Any) -> Any:
        return json_.loads(*args, **kwargs)

    def dumps(self, *args: Any, **kwargs: Any) -> ScriptSafe:
        return ScriptSafe(json_.dumps(*args, **kwargs))


scriptsafe = ScriptSafeJSON()
