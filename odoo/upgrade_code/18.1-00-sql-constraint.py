"""Convert ``_sql_constraints`` lists to ``models.Constraint`` attributes.

TESTED: ``odoo/tools/tests/test_upgrade_code_sql_constraint.py``.

Two bugs were fixed here in 2026-08, both of which corrupted the tree this ran
on; the guards that prevent them are commented inline and are not incidental:

* ``ast.literal_eval`` raises **ValueError** (not ``SyntaxError``) for a
  non-literal node, and the commonest real entry carries a translated message
  ``_('...')`` — a Call. The uncaught ValueError aborted the entire run partway
  through the file list, with earlier files already rewritten on disk.
* The rewrite names each constraint ``_{name}``, so a constraint called ``name``
  emitted ``_name = models.Constraint(...)``, silently redefining the model's
  own ``_name``. Nineteen ``BaseModel`` attributes were reachable this way.

Unconvertible statements are now left in place for a human rather than
half-rewritten. See ``odoo/cli/upgrade_code.py`` before running this.
"""

import ast
import json
import logging
import re
import typing

if typing.TYPE_CHECKING:
    from odoo.cli.upgrade_code import FileManager


#: Attributes ``BaseModel`` defines that ``_{constraint_name}`` would shadow.
#: Derived by hand from ``BaseModel`` rather than imported, because upgrade_code
#: scripts run as standalone source rewriters against OTHER checkouts and must
#: not depend on the ORM being importable.
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
            # ValueError, not just SyntaxError: ast.literal_eval raises it for
            # any NON-LITERAL node, and the single most common form of a real
            # _sql_constraints entry is a translated message --
            #     ('uniq', 'unique(code)', _('Code must be unique'))
            # -- whose third element is a Call. Catching only SyntaxError let
            # that ValueError escape build_sql_object, out of re.sub, out of
            # `upgrade`, and abort the entire run partway through the file list,
            # leaving everything already processed rewritten on disk.
            return match.group(0)
        result = []
        for name, definition, *messages in constraints:
            if f"_{name}" in _RESERVED_MODEL_ATTRIBUTES:
                # `_{name}` is how this script names the new Constraint, so a
                # constraint called "name" emits `_name = models.Constraint(...)`
                # -- silently REDEFINING the model's own _name and destroying
                # its identity. Same for _table, _inherit, _order and the rest.
                # Leave the whole statement for a human.
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
