import logging
from typing import Any, Self

from odoo import api, fields, models, tools
from odoo.api import ValuesType
from odoo.exceptions import AccessError
from odoo.tools import SQL

from .ir_model_common import (
    ACCESS_ERROR_GROUPS,
    ACCESS_ERROR_HEADER,
    ACCESS_ERROR_NOGROUP,
    ACCESS_ERROR_RESOLUTION,
)

_logger = logging.getLogger(__name__)


class IrModelAccess(models.Model):
    """Per-model CRUD access control list (ACL) entry."""

    _name = "ir.model.access"
    _description = "Model Access"
    _order = "model_id,group_id,name,id"
    _allow_sudo_commands = False
    # Single source of truth for the four CRUD modes: mode name -> SQL column.
    # Both mode validation and the ``perm_*`` column names derive from these keys.
    _PERM_COLUMNS = {
        "read": SQL("a.perm_read"),
        "write": SQL("a.perm_write"),
        "create": SQL("a.perm_create"),
        "unlink": SQL("a.perm_unlink"),
    }

    name = fields.Char(required=True, index=True)
    active = fields.Boolean(
        default=True,
        help="If you uncheck the active field, it will disable the ACL without deleting it (if you delete a native ACL, it will be re-created when you reload the module).",
    )
    model_id = fields.Many2one(
        "ir.model",
        string="Model",
        required=True,
        index=True,
        ondelete="cascade",
    )
    group_id = fields.Many2one(
        "res.groups", string="Group", ondelete="restrict", index=True
    )
    perm_read = fields.Boolean(string="Read Access")
    perm_write = fields.Boolean(string="Write Access")
    perm_create = fields.Boolean(string="Create Access")
    perm_unlink = fields.Boolean(string="Delete Access")

    @classmethod
    def _check_access_mode(cls, mode: str) -> None:
        """Raise ``ValueError`` unless ``mode`` is one of the four CRUD access
        modes (the keys of :attr:`_PERM_COLUMNS`)."""
        if mode not in cls._PERM_COLUMNS:
            raise ValueError(
                f"Invalid access mode {mode!r}: expected one of {tuple(cls._PERM_COLUMNS)}."
            )

    @api.model
    def group_names_with_access(self, model_name: str, access_mode: str) -> list[str]:
        """Return the names of visible groups granted ``access_mode`` on ``model_name``.

        :rtype: list[str]
        """
        self._check_access_mode(access_mode)
        lang = self.env.lang or "en_US"
        # Cast parameter to text so psycopg3 can infer the type for jsonb->> operators
        # without resorting to embedding the value as a raw SQL literal.
        perm_column = SQL.identifier(f"perm_{access_mode}")
        self.env.cr.execute(
            SQL(
                """
            SELECT COALESCE(c.name->>(%s::text), c.name->>'en_US'), COALESCE(g.name->>(%s::text), g.name->>'en_US')
              FROM ir_model_access a
              JOIN ir_model m ON (a.model_id = m.id)
              JOIN res_groups g ON (a.group_id = g.id)
         LEFT JOIN res_groups_privilege c ON (c.id = g.privilege_id)
             WHERE m.model = %s
               AND a.active = TRUE
               AND %s = TRUE
          ORDER BY COALESCE(c.name->>(%s::text), c.name->>'en_US') NULLS LAST, COALESCE(g.name->>(%s::text), g.name->>'en_US')
            """,
                lang,
                lang,
                model_name,
                perm_column,
                lang,
                lang,
            )
        )
        return [f"{x[0]}/{x[1]}" if x[0] else x[1] for x in self.env.cr.fetchall()]

    @api.model
    @tools.ormcache("model_name", "access_mode", cache="stable")
    def _get_access_groups(self, model_name: str, access_mode: str = "read") -> Any:
        """Return the group expression for users who have ``access_mode`` on ``model_name``."""
        self._check_access_mode(access_mode)
        model = self.env["ir.model"]._get(model_name)
        accesses = self.sudo().search(
            [
                (f"perm_{access_mode}", "=", True),
                ("model_id", "=", model.id),
            ]
        )

        group_definitions = self.env["res.groups"]._get_group_definitions()
        if not accesses:
            return group_definitions.empty
        if not all(
            access.group_id for access in accesses
        ):  # there is some global access
            return group_definitions.universe
        return group_definitions.from_ids(accesses.group_id.ids)

    # Keyed on the user's group set (not uid): the result depends only on the
    # groups, so same-group users share one entry and per-user churn can't evict
    # it. _get_group_ids() is itself ormcached and returns a stable id tuple.
    @tools.ormcache("self.env.user._get_group_ids()", "mode")
    def _get_allowed_models(self, mode: str = "read") -> frozenset[str]:
        self._check_access_mode(mode)

        group_ids = self.env.user._get_group_ids()
        self.flush_model()
        rows = self.env.execute_query(
            SQL(
                """
            SELECT m.model
              FROM ir_model_access a
              JOIN ir_model m ON (m.id = a.model_id)
             WHERE %s
               AND a.active
               AND (
                    a.group_id IS NULL OR
                    a.group_id = ANY(%s)
                )
            GROUP BY m.model
        """,
                self._PERM_COLUMNS[mode],
                list(group_ids),
            )
        )

        return frozenset(v[0] for v in rows)

    @api.model
    def check(
        self, model: str, mode: str = "read", raise_exception: bool = True
    ) -> bool:
        if self.env.su:
            # User root has all accesses
            return True

        if not isinstance(model, str):
            raise TypeError(
                f"Model name must be a string, got {type(model).__name__}: {model!r}"
            )

        if model not in self.env:
            # A typo'd/unknown model is a programming error, not an access
            # denial: raise a clear error rather than a generic AccessError.
            # The lenient path stays for raise_exception=False callers, which
            # legitimately probe models that may not be loaded (e.g. stale
            # ir.ui.menu/ir.actions visibility checks).
            if raise_exception:
                raise ValueError(
                    f"Unknown model {model!r}: it does not exist in the registry"
                    " (check for a typo or a missing/uninstalled module)."
                )
            _logger.warning("Missing model %s", model)
            return False

        has_access = model in self._get_allowed_models(mode)
        if not has_access and raise_exception:
            raise self._make_access_error(model, mode) from None
        return has_access

    def _make_access_error(self, model: str, mode: str) -> AccessError:
        """Return the exception corresponding to an access error."""
        _logger.info(
            "Access Denied by ACLs for operation: %s, uid: %s, model: %s",
            mode,
            self.env.uid,
            model,
        )

        operation_error = str(ACCESS_ERROR_HEADER[mode]) % {
            "document_kind": self.env["ir.model"]._get(model).name or model,
            "document_model": model,
        }

        groups = "\n".join(
            f"\t- {g}" for g in self.group_names_with_access(model, mode)
        )
        if groups:
            group_info = str(ACCESS_ERROR_GROUPS) % {"groups_list": groups}
        else:
            group_info = str(ACCESS_ERROR_NOGROUP)

        resolution_info = str(ACCESS_ERROR_RESOLUTION)

        return AccessError(
            operation_error + "\n\n" + group_info + "\n\n" + resolution_info
        )

    @api.model
    def call_cache_clearing_methods(self) -> None:
        self.env.invalidate_all()
        # Clearing "stable" cascades to the "default" group (see ``_CACHES_BY_KEY``
        # in the registry), invalidating both _get_access_groups (stable) and
        # _get_allowed_models (default). Narrowing to "default" would leave
        # _get_access_groups cached and hand out stale ACLs.
        self.env.registry.clear_cache("stable")

    #
    # Check rights on actions
    #
    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        self.call_cache_clearing_methods()
        for vals in vals_list:
            # An access-granting ACL with no group grants that access to every
            # user (deprecated global access). ``group_id`` defaults to NULL, so
            # an omitted key is the same global grant as an explicit falsy one --
            # both must warn.
            if not vals.get("group_id") and any(
                vals.get(f"perm_{mode}") for mode in self._PERM_COLUMNS
            ):
                _logger.warning(
                    "Rule %s has no group, this is a deprecated feature. Every access-granting rule should specify a group.",
                    vals.get("name"),
                )
        return super().create(vals_list)

    def write(self, vals: dict[str, Any]) -> bool:
        self.call_cache_clearing_methods()
        return super().write(vals)

    def unlink(self) -> bool:
        self.call_cache_clearing_methods()
        return super().unlink()
