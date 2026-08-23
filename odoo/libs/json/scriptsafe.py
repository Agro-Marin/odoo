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


#: The characters that can break out of a `<script>` block, or that a JS
#: parser treats as a line terminator inside a string literal.  Compiled at
#: module level: this runs once per JSON payload embedded in a template.
_SCRIPTSAFE_RE = re.compile(r"[<>&\u2028\u2029]")


class ScriptSafe(str):
    __slots__ = ()

    def __html__(self) -> markupsafe.Markup:
        return markupsafe.Markup(
            _SCRIPTSAFE_RE.sub(lambda m: JSON_SCRIPTSAFE_MAPPER[m[0]], self)
        )


class ScriptSafeJSON:
    def loads(self, *args: Any, **kwargs: Any) -> Any:
        return json_.loads(*args, **kwargs)

    def dumps(self, *args: Any, **kwargs: Any) -> ScriptSafe:
        return ScriptSafe(json_.dumps(*args, **kwargs))


scriptsafe = ScriptSafeJSON()
