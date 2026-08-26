import ast
import json
import logging
import re
import typing

if typing.TYPE_CHECKING:
    from odoo.cli.upgrade_code import FileManager


_RESERVED_MODEL_ATTRIBUTES = frozenset(
    {
        "_abstract",
        "_active_name",
        "_auto",
        "_check_company_auto",
        "_custom",
        "_depends",
        "_description",
        "_fold_name",
        "_inherit",
        "_inherits",
        "_module",
        "_name",
        "_order",
        "_parent_name",
        "_parent_store",
        "_rec_name",
        "_register",
        "_table",
        "_transient",
    }
)


def _models_in_scope(source: str) -> bool:
    """Whether ``models`` is a name this file can already reach.

    The rewrite emits ``models.Constraint(...)``. A model module that reaches
    for the class directly -- ``from odoo.orm.models import Model`` -- has no
    ``models`` in scope, so the rewritten file raised NameError on import.

    Importing it counts, and so does merely reading it: a file whose class
    line is ``class M(models.Model)`` resolves the name at runtime whatever
    the import looks like.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return True  # unparseable: leave the decision to build_sql_object
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "models":
            return True
        if isinstance(node, ast.ImportFrom):
            if any((a.asname or a.name) == "models" for a in node.names):
                return True
        elif isinstance(node, ast.Import):
            if any(
                (a.asname or a.name.partition(".")[0]) == "models" for a in node.names
            ):
                return True
    return False


def upgrade(file_manager: FileManager) -> None:
    log = logging.getLogger(__name__)
    # The closing `]` must end the statement. Bounded by `[^\]]+` the pattern
    # cannot span a `]`, so `_sql_constraints = [...] + EXTRA` used to match the
    # list alone and emit `models.Constraint(...) + EXTRA`, dropping EXTRA's
    # constraints and leaving code that raises TypeError on import.
    # The tail is a lookahead so the match still ends at `]`: consuming it would
    # delete a trailing comment along with the statement it annotates.
    sql_expression_re = re.compile(
        r"\b_sql_constraints\s*=\s*\[([^\]]+)](?=\s*(?:#[^\n]*)?$)", re.MULTILINE
    )
    # Anything still holding the old name after the pass is unconverted, whether
    # the pattern declined to match it or `build_sql_object` handed it back.
    leftover_re = re.compile(r"\b_sql_constraints\b")
    ind = " " * 4

    def build_sql_object(match: re.Match[str]) -> str:
        try:
            constraints = ast.literal_eval("[" + match.group(1) + "]")
        except SyntaxError, ValueError:
            return match.group(0)
        result = []
        for name, definition, *messages in constraints:
            if f"_{name}" in _RESERVED_MODEL_ATTRIBUTES:
                log.warning(
                    "%s: constraint %r would clobber the model attribute %r; "
                    "left unconverted",
                    file.path,
                    name,
                    f"_{name}",
                )
                return match.group(0)
            message = messages[0] if messages else ""
            constructor = "Constraint"
            if message:
                # `ensure_ascii=False`: the default turns every accented
                # character in a constraint message into a `\uXXXX` escape.
                message_repr = json.dumps(message, ensure_ascii=False)
                args = f"\n{ind * 2}{definition!r},\n{ind * 2}{message_repr},\n{ind}"
            elif len(definition) > 60:
                args = f"\n{ind * 2}{definition!r}"
            else:
                args = repr(definition)
            result.append(f"_{name} = models.{constructor}({args})")
        return f"\n{ind}".join(result)

    for file in file_manager:
        if file.path.suffix != ".py":
            continue
        content = file.content
        if not leftover_re.search(content):
            continue
        if not _models_in_scope(content):
            log.warning(
                "%s: no `models` import to hang `models.Constraint` on; "
                "left unconverted",
                file.path,
            )
            continue
        content = sql_expression_re.sub(build_sql_object, content)
        if leftover_re.search(content):
            log.warning("Failed to replace in file %s", file.path)
        file.content = content
