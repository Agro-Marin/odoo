"""This code is what let us use ES6-style modules in odoo.
Classic Odoo modules are composed of a top-level :samp:`odoo.define({name},{dependencies},{body_function})` call.
This processor will take files starting with an `@odoo-module` annotation (in a comment) and convert them to classic modules.
If any file has the ``/** odoo-module */`` on top of it, it will get processed by this class.
It performs several operations to get from ES6 syntax to the usual odoo one with minimal changes.
This is done on the fly, this not a pre-processing tool.

Caveat: This is done without a full parser, only using regex. One can only expect to cover as much edge cases
as possible with reasonable limitations. Also, this only changes imports and exports, so all JS features used in
the original source need to be supported by the browsers.
"""

import re
from collections.abc import Callable
from functools import partial

from odoo.libs.collections import OrderedSet


def transpile_javascript(url: str, content: str) -> str:
    """Transpile the code from native JS modules to custom odoo modules.

    :param content: The original source code
    :param url: The url of the file in the project
    :return: The transpiled source code
    """
    module_path = url_to_module_path(url)
    legacy_odoo_define = get_aliased_odoo_define_content(module_path, content)
    dependencies = OrderedSet()
    # The order of the operations does sometimes matter.
    steps = [
        convert_all_imports,
        convert_from_export,
        convert_star_from_export,
        remove_index,
        partial(convert_relative_require, url, dependencies),
        convert_all_exports,
        partial(wrap_with_qunit_module, url),
        partial(wrap_with_odoo_define, module_path, dependencies),
        partial(convert_t, url),
    ]
    for s in steps:
        content = s(content)
    if legacy_odoo_define:
        content += legacy_odoo_define
    return content


URL_RE = re.compile(
    r"""
    /?(?P<module>\S+)    # /module name
    /([\S/]*/)?static/   # ... /static/
    (?P<type>src|tests|lib)  # src, test, or lib file
    (?P<url>/[\S/]*)     # URL (/...)
    """,
    re.VERBOSE,
)


def url_to_module_path(url: str) -> str:
    """Odoo modules each have a name. (odoo.define("<the name>", [<dependencies>], function (require) {...});
    It is used in to be required later. (const { something } = require("<the name>").
    The transpiler transforms the url of the file in the project to this name.
    It takes the module name and add a @ on the start of it, and map it to be the source of the static/src (or
    static/tests, or static/lib) folder in that module.

    in: web/static/src/one/two/three.js
    out: @web/one/two/three.js
    The module would therefore be defined and required by this path.

    :param url: an url in the project
    :return: a special path starting with @<module-name>.
    """
    match = URL_RE.match(url)
    if match:
        url = match["url"]
        if url.endswith(("/index.js", "/index")):
            url, _ = url.rsplit("/", 1)
        url = url.removesuffix(".js")
        match match["type"]:
            case "src":
                return f"@{match['module']}{url}"
            case "lib":
                return f"@{match['module']}/../lib{url}"
            case _:
                return f"@{match['module']}/../tests{url}"
    else:
        raise ValueError(
            f"The js file {url!r} must be in the folder '/static/src' or '/static/lib' or '/static/test'"
        )


def wrap_with_qunit_module(url: str, content: str) -> str:
    """Wraps the test file content (source code) with the QUnit.module('module_name', function() {...})."""
    if "tests" in url and re.search(r"QUnit\.(test|debug|only)\(", content):
        match = URL_RE.match(url)
        return f"""QUnit.module("{match["module"]}", function() {{{content}}});"""
    return content


def wrap_with_odoo_define(
    module_path: str, dependencies: OrderedSet, content: str
) -> str:
    """Wraps the current content (source code) with the odoo.define call.
    It adds as a second argument the list of dependencies.
    Should logically be called once all other operations have been performed.
    """
    return f"""odoo.define({module_path!r}, {list(dependencies)}, function (require) {{
'use strict';
let __exports = {{}};
{content}
return __exports;
}});
"""


# ---------------------------------------------------------------------------
# Combined single-pass export-declaration converter
# ---------------------------------------------------------------------------
# Handles: export function, export class, export let/const/var,
# export { ... }, and all export default variants in one pass.
# Re-exports (export ... from) are handled separately since they run earlier
# in the pipeline (before remove_index and convert_relative_require).

_COMBINED_EXPORT_RE = re.compile(
    r"""
    ^(?P<space>\s*)
    export\s+
    (?:
        default\s+(?P<df_type>(?:async\s+)?function)\s+(?P<df_name>[\w$]+)   # export default [async] function
        |
        default\s+(?P<dc_type>class)\s+(?P<dc_name>[\w$]+)                   # export default class
        |
        default\s+(?P<dv_type>let|const|var)\s+(?P<dv_name>[\w$]+)\s*        # export default let/const/var
        |
        default(?P<d_assign>\s+[\w$]+\s*=)?                                  # export default [X =]
        |
        (?P<f_type>(?:async\s+)?function)\s+(?P<f_name>[\w$]+)               # export function/async function
        |
        (?P<c_type>class)\s+(?P<c_name>[\w$]+)                               # export class
        |
        (?P<v_type>let|const|var)\s+(?P<v_name>[\w$]+)                        # export let/const/var
        |
        (?P<obj>{[\w$\s,]+})                                                  # export { a, b, c as x }
    )
    """,
    re.MULTILINE | re.VERBOSE,
)


def _export_replacement(match: re.Match[str]) -> str:
    """Dispatch to the appropriate export conversion based on which group matched."""
    space = match["space"]

    if match["df_name"]:
        name = match["df_name"]
        ftype = match["df_type"]
        return f'{space}__exports[Symbol.for("default")] = {name}; {ftype} {name}'

    if match["dc_name"]:
        name = match["dc_name"]
        return f'{space}const {name} = __exports[Symbol.for("default")] = class {name}'

    if match["dv_name"]:
        name = match["dv_name"]
        vtype = match["dv_type"]
        return f'{space}{vtype} {name} = __exports[Symbol.for("default")]'

    # Catch-all: export default [X =]
    if match["d_assign"] is not None or (
        not match["f_name"]
        and not match["c_name"]
        and not match["v_name"]
        and not match["obj"]
    ):
        return f'{space}__exports[Symbol.for("default")] ='

    if match["f_name"]:
        name = match["f_name"]
        ftype = match["f_type"]
        return f"{space}__exports.{name} = {name}; {ftype} {name}"

    if match["c_name"]:
        name = match["c_name"]
        return f"{space}const {name} = __exports.{name} = class {name}"

    if match["v_name"]:
        name = match["v_name"]
        vtype = match["v_type"]
        return f"{space}{vtype} {name} = __exports.{name}"

    if match["obj"]:
        parts = [convert_as(val) for val in match["obj"][1:-1].split(",")]
        joined = ", ".join(parts)
        joined = re.sub(r" +\n", "\n", joined)
        return f"{space}Object.assign(__exports, {{{joined}}})"

    return match.group(0)


def convert_all_exports(content: str) -> str:
    """Convert all export declarations to __exports assignments in a single regex pass.

    Replaces the 5 sequential export-conversion functions (convert_export_function,
    convert_export_class, convert_variable_export, convert_object_export,
    convert_default_export) with one combined alternation regex.
    """
    if "export" not in content:
        return content
    return _COMBINED_EXPORT_RE.sub(_export_replacement, content)


# ---------------------------------------------------------------------------
# Individual export converters (kept for external callers / tests)
# ---------------------------------------------------------------------------

EXPORT_FCT_RE = re.compile(
    r"""
    ^
    (?P<space>\s*)                          # space and empty line
    export\s+                               # export
    (?P<type>(async\s+)?function)\s+        # async function or function
    (?P<identifier>[\w$]+)                  # name of the function
    """,
    re.MULTILINE | re.VERBOSE,
)


def convert_export_function(content: str) -> str:
    """Transpile functions that are being exported.

    .. code-block:: javascript

        // before
        export function name
        // after
       __exports.name = name; function name

        // before
        export async function name
        // after
        __exports.name = name; async function name

    """
    repl = (
        r"\g<space>__exports.\g<identifier> = \g<identifier>; \g<type> \g<identifier>"
    )
    return EXPORT_FCT_RE.sub(repl, content)


EXPORT_CLASS_RE = re.compile(
    r"""
    ^
    (?P<space>\s*)                          # space and empty line
    export\s+                               # export
    (?P<type>class)\s+                      # class
    (?P<identifier>[\w$]+)                  # name of the class
    """,
    re.MULTILINE | re.VERBOSE,
)


def convert_export_class(content: str) -> str:
    """Transpile classes that are being exported.

    .. code-block:: javascript

        // before
        export class name
        // after
        const name = __exports.name = class name

    """
    repl = r"\g<space>const \g<identifier> = __exports.\g<identifier> = \g<type> \g<identifier>"
    return EXPORT_CLASS_RE.sub(repl, content)


EXPORT_FCT_DEFAULT_RE = re.compile(
    r"""
    ^
    (?P<space>\s*)                          # space and empty line
    export\s+default\s+                     # export default
    (?P<type>(async\s+)?function)\s+        # async function or function
    (?P<identifier>[\w$]+)                  # name of the function
    """,
    re.MULTILINE | re.VERBOSE,
)


def convert_export_function_default(content: str) -> str:
    """Transpile functions that are being exported as default value.

    .. code-block:: javascript

        // before
        export default function name
        // after
        __exports[Symbol.for("default")] = name; function name

        // before
        export default async function name
        // after
        __exports[Symbol.for("default")] = name; async function name

    """
    repl = r"""\g<space>__exports[Symbol.for("default")] = \g<identifier>; \g<type> \g<identifier>"""
    return EXPORT_FCT_DEFAULT_RE.sub(repl, content)


EXPORT_CLASS_DEFAULT_RE = re.compile(
    r"""
    ^
    (?P<space>\s*)                          # space and empty line
    export\s+default\s+                     # export default
    (?P<type>class)\s+                      # class
    (?P<identifier>[\w$]+)                  # name of the class or the function
    """,
    re.MULTILINE | re.VERBOSE,
)


def convert_export_class_default(content: str) -> str:
    """Transpile classes that are being exported as default value.

    .. code-block:: javascript

        // before
        export default class name
        // after
        const name = __exports[Symbol.for("default")] = class name

    """
    repl = r"""\g<space>const \g<identifier> = __exports[Symbol.for("default")] = \g<type> \g<identifier>"""
    return EXPORT_CLASS_DEFAULT_RE.sub(repl, content)


GETTEXT_RE = re.compile(
    r"""
    ^
    \s*const\s*{
    (?:\s*\w*\s*,)*
    \s*(_t)\s*
    (?:,\s*\w*\s*)*,?\s*
    }\s*=\s*require\("@web/core/l10n/translation"\);$
""",
    re.MULTILINE | re.VERBOSE,
)


T_FN_RE = re.compile(
    r"""
    ^
    \s*const\s*{
    (?:\s*\w*\s*,)*
    \s*(appTranslateFn)\s*
    (?:,\s*\w*\s*)*,?\s*
    }\s*=\s*require\("@web/core/l10n/translation"\);$
""",
    re.MULTILINE | re.VERBOSE,
)


def convert_t(url: str, content: str) -> str:
    if url.endswith(".test.js"):
        return content
    if '@web/core/l10n/translation"' not in content:
        return content

    module_name = URL_RE.match(url)["module"]
    has_import_of_appTranslateFn = bool(T_FN_RE.search(content))

    def rename_gettext(match_: re.Match[str]) -> str:
        if has_import_of_appTranslateFn:
            renamed_import = match_.group(0).replace("_t", "__not_defined__")
        else:
            renamed_import = match_.group(0).replace("_t", "appTranslateFn")
        renamed_import += f"""const _t = (str, ...args) => appTranslateFn(str, "{module_name}", ...args);"""
        return renamed_import

    return GETTEXT_RE.sub(rename_gettext, content)


EXPORT_VAR_RE = re.compile(
    r"""
    ^
    (?P<space>\s*)              # space and empty line
    export\s+                   # export
    (?P<type>let|const|var)\s+  # let or cont or var
    (?P<identifier>[\w$]+)      # variable name
    """,
    re.MULTILINE | re.VERBOSE,
)


def convert_variable_export(content: str) -> str:
    """Transpile variables that are being exported.

    .. code-block:: javascript

        // before
        export let name
        // after
        let name = __exports.name
        // (same with var and const)

    """
    repl = r"\g<space>\g<type> \g<identifier> = __exports.\g<identifier>"
    return EXPORT_VAR_RE.sub(repl, content)


EXPORT_DEFAULT_VAR_RE = re.compile(
    r"""
    ^
    (?P<space>\s*)              # space and empty line
    export\s+default\s+         # export default
    (?P<type>let|const|var)\s+  # let or const or var
    (?P<identifier>[\w$]+)\s*   # variable name
    """,
    re.MULTILINE | re.VERBOSE,
)


def convert_variable_export_default(content: str) -> str:
    """Transpile the variables that are exported as default values.

    .. code-block:: javascript

        // before
        export default let name
        // after
        let name = __exports[Symbol.for("default")]

    """
    repl = r"""\g<space>\g<type> \g<identifier> = __exports[Symbol.for("default")]"""
    return EXPORT_DEFAULT_VAR_RE.sub(repl, content)


EXPORT_OBJECT_RE = re.compile(
    r"""
    ^
    (?P<space>\s*)                      # space and empty line
    export\s*                           # export
    (?P<object>{[\w$\s,]+})             # { a, b, c as x, ... }
    """,
    re.MULTILINE | re.VERBOSE,
)


def convert_object_export(content: str) -> str:
    """Transpile exports of multiple elements.

    .. code-block:: javascript

        // before
        export { a, b, c as x }
        // after
        Object.assign(__exports, { a, b, x: c })
    """
    if "export" not in content:
        return content

    def repl(matchobj: re.Match[str]) -> str:
        parts = [convert_as(val) for val in matchobj["object"][1:-1].split(",")]
        joined = ", ".join(parts)
        # Remove trailing spaces before newlines (from multiline exports)
        joined = re.sub(r" +\n", "\n", joined)
        object_process = "{" + joined + "}"
        space = matchobj["space"]
        return f"{space}Object.assign(__exports, {object_process})"

    return EXPORT_OBJECT_RE.sub(repl, content)


EXPORT_FROM_RE = re.compile(
    r"""
    ^
    (?P<space>\s*)                      # space and empty line
    export\s*                           # export
    (?P<object>{[\w$\s,]+})\s*          # { a, b, c as x, ... }
    from\s*                             # from
    (?P<path>(?P<quote>["'`])([^"'`]+)(?P=quote))   # "file path" ("some/path.js")
    """,
    re.MULTILINE | re.VERBOSE,
)


def convert_from_export(content: str) -> str:
    """Transpile exports coming from another source.

    .. code-block:: javascript

        // before
        export { a, b, c as x } from "some/path.js"
        // after
        { a, b, c } = {require("some/path.js"); Object.assign(__exports, { a, b, x: c });}
    """
    if "export" not in content:
        return content

    def repl(matchobj: re.Match[str]) -> str:
        object_clean = (
            "{"
            + ",".join([remove_as(val) for val in matchobj["object"][1:-1].split(",")])
            + "}"
        )
        object_process = (
            "{"
            + ", ".join(
                [convert_as(val) for val in matchobj["object"][1:-1].split(",")]
            )
            + "}"
        )
        space = matchobj["space"]
        path = matchobj["path"]
        return f"{space}{{const {object_clean} = require({path});Object.assign(__exports, {object_process})}}"

    return EXPORT_FROM_RE.sub(repl, content)


EXPORT_STAR_FROM_RE = re.compile(
    r"""
    ^
    (?P<space>\s*)                      # space and empty line
    export\s*\*\s*from\s*               # export * from
    (?P<path>(?P<quote>["'`])([^"'`]+)(?P=quote))   # "file path" ("some/path.js")
    """,
    re.MULTILINE | re.VERBOSE,
)


def convert_star_from_export(content: str) -> str:
    """Transpile exports star coming from another source.

    .. code-block:: javascript

        // before
        export * from "some/path.js"
        // after
        Object.assign(__exports, require("some/path.js"))
    """
    if "export *" not in content:
        return content
    repl = r"\g<space>Object.assign(__exports, require(\g<path>))"
    return EXPORT_STAR_FROM_RE.sub(repl, content)


EXPORT_DEFAULT_RE = re.compile(
    r"""
    ^
    (?P<space>\s*)      # space and empty line
    export\s+default    # export default
    (\s+[\w$]+\s*=)?    # something (optional)
    """,
    re.MULTILINE | re.VERBOSE,
)


def convert_default_export(content: str) -> str:
    """This function handles the default exports.
    Either by calling another operation with a TRUE flag, and if any default is left, doing a simple replacement.

    (see convert_export_function_or_class_default and convert_variable_export_default).
    +
    .. code-block:: javascript

        // before
        export default
        // after
        __exports[Symbol.for("default")] =

    .. code-block:: javascript

        // before
        export default something =
        // after
        __exports[Symbol.for("default")] =
    """
    if "export default" not in content:
        return content
    new_content = convert_export_function_default(content)
    new_content = convert_export_class_default(new_content)
    new_content = convert_variable_export_default(new_content)
    repl = r"""\g<space>__exports[Symbol.for("default")] ="""
    return EXPORT_DEFAULT_RE.sub(repl, new_content)


# ---------------------------------------------------------------------------
# Combined single-pass import converter
# ---------------------------------------------------------------------------
# All ES6 import forms are mutually exclusive based on what follows
# ``import\s+`` (brace, star, identifier+comma, identifier+from, bare path).
# Combining them into one alternation regex avoids scanning the file 7 times
# (one per form) and yields ~4× speedup on the import phase.
#
# Alternation order matters — more specific patterns must come first so that
# Python's ordered alternation picks the right branch:
#   1. default + named:  ``import X, { a, b } from "path"``
#   2. default + star:   ``import X, * as Y from "path"``
#   3. basic named:      ``import { a, b } from "path"``
#   4. star:             ``import * as X from "path"``
#   5. legacy default:   ``import X from "addon.name"``  (path ≠ @/.)
#   6. default:          ``import X from "path"``
#   7. unnamed (bare):   ``import "path"``

IS_PATH_LEGACY_RE = re.compile(r"""(?P<quote>["'`])([^@\."'`][^"'`]*)(?P=quote)""")

_COMBINED_IMPORT_RE = re.compile(
    r"""
    ^(?P<space>\s*)
    import\s+
    (?:
        (?P<dn_default>[\w$]+)\s*,\s*                                   # 1: default + named
            (?P<dn_named>{[\s\w$,]+})\s*from\s*
            (?P<dn_path>(?P<dnq>["'`])[^"'`]+(?P=dnq))
        |
        (?P<ds_default>[\w$]+)\s*,\s*                                   # 2: default + star
            \*\s+as\s+(?P<ds_alias>[\w$]+)\s*from\s*
            (?P<ds_path>[^;\n]+)
        |
        (?P<basic_obj>{[\s\w$,]+})\s*from\s*                           # 3: basic named
            (?P<basic_path>(?P<bq>["'`])[^"'`]+(?P=bq))
        |
        \*\s+as\s+(?P<star_id>[\w$]+)\s*from\s*                        # 4: star
            (?P<star_path>[^;\n]+)
        |
        (?P<legacy_id>[\w$]+)\s*from\s*                                 # 5: legacy default
            (?P<legacy_path>(?P<lq>["'`])[^@\."'`][^"'`]*(?P=lq))
        |
        (?P<def_id>[\w$]+)\s*from\s*                                    # 6: default
            (?P<def_path>(?P<dq>["'`])[^"'`]+(?P=dq))
        |
        (?P<unnamed_path>[^;\n]+)                                       # 7: unnamed (bare)
    )
    """,
    re.MULTILINE | re.VERBOSE,
)


def _import_replacement(match: re.Match[str]) -> str:
    """Dispatch to the appropriate import conversion based on which group matched."""
    space = match["space"]

    if match["dn_default"]:
        # import X, { a, b } from "path"
        default_name = match["dn_default"]
        named = match["dn_named"].replace(" as ", ": ")
        path = match["dn_path"]
        if IS_PATH_LEGACY_RE.match(path):
            return (
                f"{space}const {default_name} = require({path});\n"
                f"{space}const {named} = {default_name}"
            )
        named = f'{{ [Symbol.for("default")]: {default_name},{named[1:]}'
        return f"{space}const {named} = require({path})"

    if match["ds_default"]:
        # import X, * as Y from "path"
        alias = match["ds_alias"]
        path = match["ds_path"]
        default_name = match["ds_default"]
        return (
            f"{space}const {alias} = require({path});\n"
            f'{space}const {default_name} = {alias}[Symbol.for("default")]'
        )

    if match["basic_obj"]:
        # import { a, b, c as x } from "path"
        obj = match["basic_obj"].replace(" as ", ": ")
        return f"{space}const {obj} = require({match['basic_path']})"

    if match["star_id"]:
        # import * as X from "path"
        return f"{space}const {match['star_id']} = require({match['star_path']})"

    if match["legacy_id"]:
        # import X from "addon.module_name"
        return f"{space}const {match['legacy_id']} = require({match['legacy_path']})"

    if match["def_id"]:
        # import X from "path"
        return f'{space}const {match["def_id"]} = require({match["def_path"]})[Symbol.for("default")]'

    # unnamed bare import: import "path"
    return f"{space}require({match['unnamed_path']})"


def convert_all_imports(content: str) -> str:
    """Convert all ES6 import statements to require() calls in a single regex pass.

    Replaces the 7 sequential import-conversion functions with one combined
    alternation regex, reducing file scans from 7× to 1×.
    """
    return _COMBINED_IMPORT_RE.sub(_import_replacement, content)


# ---------------------------------------------------------------------------
# Individual import converters (kept for external callers / tests)
# ---------------------------------------------------------------------------

IMPORT_BASIC_RE = re.compile(
    r"""
    ^
    (?P<space>\s*)                      # space and empty line
    import\s+                           # import
    (?P<object>{[\s\w$,]+})\s*          # { a, b, c as x, ... }
    from\s*                             # from
    (?P<path>(?P<quote>["'`])([^"'`]+)(?P=quote))   # "file path" ("some/path")
    """,
    re.MULTILINE | re.VERBOSE,
)


def convert_basic_import(content: str) -> str:
    """Transpile the simpler import call.

    .. code-block:: javascript

        // before
        import { a, b, c as x } from "some/path"
        // after
        const {a, b, c: x} = require("some/path")
    """

    def repl(matchobj: re.Match[str]) -> str:
        new_object = matchobj["object"].replace(" as ", ": ")
        return f"{matchobj['space']}const {new_object} = require({matchobj['path']})"

    return IMPORT_BASIC_RE.sub(repl, content)


IMPORT_LEGACY_DEFAULT_RE = re.compile(
    r"""
    ^
    (?P<space>\s*)                                      # space and empty line
    import\s+                                           # import
    (?P<identifier>[\w$]+)\s*                           # default variable name
    from\s*                                             # from
    (?P<path>(?P<quote>["'`])([^@\."'`][^"'`]*)(?P=quote))  # legacy alias file ("addon_name.module_name" or "some/path")
    """,
    re.MULTILINE | re.VERBOSE,
)


def convert_legacy_default_import(content: str) -> str:
    """Transpile legacy imports (that were used as they were default import).
    Legacy imports means that their name is not a path but a <addon_name>.<module_name>.
    It requires slightly different processing.

    .. code-block:: javascript

        // before
        import module_name from "addon.module_name"
        // after
        const module_name = require("addon.module_name")
    """
    repl = r"""\g<space>const \g<identifier> = require(\g<path>)"""
    return IMPORT_LEGACY_DEFAULT_RE.sub(repl, content)


IMPORT_DEFAULT = re.compile(
    r"""
    ^
    (?P<space>\s*)                      # space and empty line
    import\s+                           # import
    (?P<identifier>[\w$]+)\s*           # default variable name
    from\s*                             # from
    (?P<path>(?P<quote>["'`])([^"'`]+)(?P=quote))   # "file path" ("some/path")
    """,
    re.MULTILINE | re.VERBOSE,
)


def convert_default_import(content: str) -> str:
    """Transpile the default import call.

    .. code-block:: javascript

        // before
        import something from "some/path"
        // after
        const something = require("some/path")[Symbol.for("default")]
    """
    repl = (
        r"""\g<space>const \g<identifier> = require(\g<path>)[Symbol.for("default")]"""
    )
    return IMPORT_DEFAULT.sub(repl, content)


IMPORT_DEFAULT_AND_NAMED_RE = re.compile(
    r"""
    ^
    (?P<space>\s*)                                  # space and empty line
    import\s+                                       # import
    (?P<default_export>[\w$]+)\s*,\s*               # default variable name,
    (?P<named_exports>{[\s\w$,]+})\s*                # { a, b, c as x, ... }
    from\s*                                         # from
    (?P<path>(?P<quote>["'`])([^"'`]+)(?P=quote))   # "file path" ("some/path")
    """,
    re.MULTILINE | re.VERBOSE,
)


def convert_default_and_named_import(content: str) -> str:
    """Transpile default and named import on one line.

    .. code-block:: javascript

        // before
        import something, { a } from "some/path";
        import somethingElse, { b } from "legacy.module";
        // after
        const { [Symbol.for("default")]: something, a } = require("some/path");
        const somethingElse = require("legacy.module");
        const { b } = somethingElse;
    """

    def repl(matchobj: re.Match[str]) -> str:
        is_legacy = IS_PATH_LEGACY_RE.match(matchobj["path"])
        new_object = matchobj["named_exports"].replace(" as ", ": ")
        if is_legacy:
            return f"""{matchobj["space"]}const {matchobj["default_export"]} = require({matchobj["path"]});
{matchobj["space"]}const {new_object} = {matchobj["default_export"]}"""
        new_object = f"""{{ [Symbol.for("default")]: {matchobj["default_export"]},{new_object[1:]}"""
        return f"{matchobj['space']}const {new_object} = require({matchobj['path']})"

    return IMPORT_DEFAULT_AND_NAMED_RE.sub(repl, content)


RELATIVE_REQUIRE_RE = re.compile(
    r"""
    ^(?P<prefix>[^/*\n]*)                         # line content before require (skip comments)
    require\((?P<quote>[\"'`])(?P<path>[^\"'`]+)(?P=quote)\)  # require("some/path")
    """,
    re.MULTILINE | re.VERBOSE,
)


def convert_relative_require(url: str, dependencies: OrderedSet, content: str) -> str:
    """Convert relative paths in require() calls to module paths (@module/...).

    Also collects all require'd paths into ``dependencies``.

    Uses a single ``re.sub`` pass with a callback instead of ``findall`` +
    per-match ``re.sub`` to avoid O(M×N) rescanning and regex injection from
    unescaped special characters in paths.

    .. code-block:: javascript

        // Relative path:
        // before
        require("./path")
        // after
        require("@module/path")

        // Non-relative path:
        // before
        require("other_alias")
        // after
        require("other_alias")
    """

    def _replace(match: re.Match[str]) -> str:
        path = match["path"]
        module_path = path
        if path.startswith(".") and "/" in path:
            module_path = relative_path_to_module_path(url, path)
        dependencies.add(module_path)
        if module_path != path:
            return f'{match["prefix"]}require("{module_path}")'
        return match.group(0)

    return RELATIVE_REQUIRE_RE.sub(_replace, content)


IMPORT_STAR = re.compile(
    r"""
    ^(?P<space>\s*)         # indentation
    import\s+\*\s+as\s+     # import * as
    (?P<identifier>[\w$]+)  # alias
    \s*from\s*              # from
    (?P<path>[^;\n]+)       # path
""",
    re.MULTILINE | re.VERBOSE,
)


def convert_star_import(content: str) -> str:
    """Transpile import star.

    .. code-block:: javascript

        // before
        import * as name from "some/path"
        // after
        const name = require("some/path")
    """
    if "import *" not in content and "import  *" not in content:
        return content
    repl = r"\g<space>const \g<identifier> = require(\g<path>)"
    return IMPORT_STAR.sub(repl, content)


IMPORT_DEFAULT_AND_STAR = re.compile(
    r"""
    ^(?P<space>\s*)                    # indentation
    import\s+                          # import
    (?P<default_export>[\w$]+)\s*,\s*  # default export name,
    \*\s+as\s+                         # * as
    (?P<named_exports_alias>[\w$]+)    # alias
    \s*from\s*                         # from
    (?P<path>[^;\n]+)                  # path
""",
    re.MULTILINE | re.VERBOSE,
)


def convert_default_and_star_import(content: str) -> str:
    """Transpile import star.

    .. code-block:: javascript

        // before
        import something, * as name from "some/path";
        // after
        const name = require("some/path");
        const something = name[Symbol.for("default")];
    """
    # Pattern requires "import X, * as" — the ", *" is highly discriminating.
    if ", *" not in content:
        return content
    repl = r"""\g<space>const \g<named_exports_alias> = require(\g<path>);
\g<space>const \g<default_export> = \g<named_exports_alias>[Symbol.for("default")]"""
    return IMPORT_DEFAULT_AND_STAR.sub(repl, content)


IMPORT_UNNAMED_RELATIVE_RE = re.compile(
    r"""
    ^(?P<space>\s*)     # indentation
    import\s+           # import
    (?P<path>[^;\n]+)   # relative path
""",
    re.MULTILINE | re.VERBOSE,
)


def convert_unnamed_relative_import(content: str) -> str:
    """Transpile relative "direct" imports. Direct meaning they are not store in a variable.

    .. code-block:: javascript

        // before
        import "some/path"
        // after
        require("some/path")
    """
    repl = r"\g<space>require(\g<path>)"
    return IMPORT_UNNAMED_RELATIVE_RE.sub(repl, content)


URL_INDEX_RE = re.compile(
    r"""
    require\s*                 # require
    \(\s*                      # (
    (?P<path>(?P<quote>["'`])([^"'`]*/index/?)(?P=quote))  # path ended by /index or /index/
    \s*\)                      # )
""",
    re.MULTILINE | re.VERBOSE,
)


def remove_index(content: str) -> str:
    """Remove in the paths the /index.js.
    We want to be able to import a module just through its directory name if it contains an index.js.
    So we no longer need to specify the index.js in the paths.
    """
    if "/index" not in content:
        return content

    def repl(matchobj: re.Match[str]) -> str:
        path = matchobj["path"]
        new_path = path[: path.rfind("/index")] + path[0]
        return f"require({new_path})"

    return URL_INDEX_RE.sub(repl, content)


def relative_path_to_module_path(url: str, path_rel: str) -> str:
    """Convert the relative path into a module path, which is more generic and
    fancy.

    :param str url:
    :param path_rel: a relative path to the current url.
    :return: module path (@module/...)
    """
    url_split = url.split("/")
    path_rel_split = path_rel.split("/")
    nb_back = len([v for v in path_rel_split if v == ".."]) + 1
    result = "/".join(
        url_split[:-nb_back] + [v for v in path_rel_split if v not in ["..", "."]]
    )
    return url_to_module_path(result)


ODOO_MODULE_RE = re.compile(
    r"""
    \/(\*|\/)                          # /* or //
    .*                                 # any comment in between (optional)
    @odoo-module                       # '@odoo-module' statement
    (?P<ignore>\s+ignore)?             # module in src | tests which should not be transpiled (optional)
    (?P<native>\s+native)?             # native ES module — skip transpilation, serve as-is (optional)
    (\s+alias=(?P<alias>[^\s*]+))?     # alias (e.g. alias=web.Widget, alias=@web/../tests/utils) (optional)
    (\s+default=(?P<default>[\w$]+))?  # no implicit default export (e.g. default=false) (optional)
""",
    re.VERBOSE,
)


def _parse_odoo_module_header(url: str, content: str) -> re.Match[str] | None:
    """Parse the ``@odoo-module`` directive from the file header.

    Returns the regex match object, or None if no directive found.
    Only scans the first 500 characters.
    """
    return ODOO_MODULE_RE.search(content[:500])


def is_odoo_module(url: str, content: str) -> bool:
    """Detect if the file is a legacy odoo module needing transpilation.

    Looks for a ``@odoo-module`` comment directive in the first 500 characters
    of the file.  Files under ``static/src/`` or ``static/tests/`` are treated
    as modules by default unless explicitly marked ``@odoo-module ignore``
    or ``@odoo-module native``.

    Uses ``re.search`` (not ``re.match``) so that preceding comments like
    ``// @ts-check`` don't shadow the directive.
    """
    result = _parse_odoo_module_header(url, content)
    if result and (result["ignore"] or result["native"]):
        return False
    addon = url.split("/")[1]
    if url.startswith((f"/{addon}/static/src", f"/{addon}/static/tests")):
        return True
    return bool(result)


def is_native_module(url: str, content: str) -> bool:
    """Detect if the file is a native ES module (``@odoo-module native``).

    Native modules skip Python transpilation entirely and are served as-is
    to the browser, which resolves their imports via an import map.
    """
    result = _parse_odoo_module_header(url, content)
    return bool(result and result["native"])


def get_native_module_alias(url: str, content: str) -> str | None:
    """Return the import map alias for a native module, if declared.

    For native modules with ``@odoo-module native alias=@odoo/hoot``,
    returns the alias specifier (``"@odoo/hoot"``).  The caller should
    add an extra import map entry mapping this alias to the module's URL
    so that ``import ... from "@odoo/hoot"`` resolves correctly.
    """
    result = _parse_odoo_module_header(url, content)
    if result and result["native"] and result["alias"]:
        return result["alias"]
    return None


def get_aliased_odoo_define_content(module_path: str, content: str) -> str | None:
    """To allow smooth transition between the new system and the legacy one, we have the possibility to
    defined an alternative module name (an alias) that will act as proxy between legacy require calls and
    new modules.

    Example:
    If we have a require call somewhere in the odoo source base being:
    > vat AbstractAction require("web.AbstractAction")
    we have a problem when we will have converted to module to ES6: its new name will be more like
    "web/chrome/abstract_action". So the require would fail !
    So we add a second small modules, an alias, as such:
    > odoo.define("web/chrome/abstract_action", ['web.AbstractAction'], function (require) {
    >  return require('web.AbstractAction')[Symbol.for("default")];
    > });

    To generate this, change your comment on the top of the file.

    .. code-block:: javascript

        // before
        /** @odoo-module */
        // after
        /** @odoo-module alias=web.AbstractAction */

    Notice that often, the legacy system acted like it did default imports. That's why we have the
    "[Symbol.for("default")];" bit. If your use case does not need this default import, just do:

    .. code-block:: javascript

        // before
        /** @odoo-module */
        // after
        /** @odoo-module alias=web.AbstractAction default=false */

    :return: the alias content to append to the source code.

    """
    matchobj = ODOO_MODULE_RE.search(content[:500])
    if matchobj:
        alias = matchobj["alias"]
        if alias:
            default_access = "" if matchobj["default"] else '[Symbol.for("default")]'
            return f"""\nodoo.define(`{alias}`, ['{module_path}'], function (require) {{
                        return require('{module_path}'){default_access};
                        }});\n"""
    return None


def convert_as(val: str) -> str:
    """Convert 'a as b' export syntax to 'b: a' object destructuring syntax."""
    parts = val.split(" as ")
    return val if len(parts) < 2 else f"{parts[1]}: {parts[0]}"


def remove_as(val: str) -> str:
    """Strip the 'as alias' part from an import/export specifier."""
    parts = val.split(" as ")
    return val if len(parts) < 2 else parts[0]
