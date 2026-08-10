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


def upgrade(file_manager: FileManager) -> None:
    log = logging.getLogger(__name__)
    sql_expression_re = re.compile(r"\b_sql_constraints\s*=\s*\[([^\]]+)]")
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
                message_repr = json.dumps(message)
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
        content = sql_expression_re.sub(build_sql_object, content)
        if sql_expression_re.search(content):
            log.warning("Failed to replace in file %s", file.path)
        file.content = content
