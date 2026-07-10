import ast
from typing import Any, Self

from odoo import api, fields, models
from odoo.api import ValuesType
from odoo.exceptions import ValidationError
from odoo.tools import SQL


class IrFilters(models.Model):
    _name = "ir.filters"
    _description = "Filters"
    _order = "model_id, name, id desc"

    name = fields.Char(string="Filter Name", required=True)
    active = fields.Boolean(default=True)
    model_id = fields.Selection(
        selection="_list_all_models",
        string="Model",
        required=True,
    )
    user_ids = fields.Many2many(
        "res.users",
        string="Users",
        ondelete="cascade",
        help="The users the filter is shared with. If empty, the filter is shared with all users.",
    )
    domain = fields.Text(default="[]", required=True)
    context = fields.Text(default="{}", required=True)
    sort = fields.Char(default="[]", required=True)
    is_default = fields.Boolean(string="Default Filter")
    action_id = fields.Many2one(
        "ir.actions.actions",
        string="Action",
        ondelete="cascade",
        help="The menu action this filter applies to. When left empty the filter applies to all menus for this model.",
    )
    embedded_action_id = fields.Many2one(
        "ir.embedded.actions",
        ondelete="cascade",
        index="btree_not_null",
        help="The embedded action this filter is applied to",
    )
    embedded_parent_res_id = fields.Integer(
        help="id of the record the filter should be applied to. Only used in combination with embedded actions"
    )

    _get_filters_index = models.Index(
        "(model_id, action_id, embedded_action_id, embedded_parent_res_id)",
    )
    # embedded_parent_res_id is only set when embedded_action_id is set. Since the
    # embedded model links to a single res_model, this ensures filter unicity per
    # embedded_parent_res_model and embedded_parent_res_id.
    _check_res_id_only_when_embedded_action = models.Constraint(
        "CHECK(NOT (embedded_parent_res_id IS NOT NULL AND embedded_action_id IS NULL))",
        "Constraint to ensure that the embedded_parent_res_id is only defined when a top_action_id is defined.",
    )
    _check_sort_json = models.Constraint(
        "CHECK(sort IS NULL OR jsonb_typeof(sort::jsonb) = 'array')",
        "Invalid sort definition",
    )

    @api.constrains("domain", "context", "sort")
    def _check_serialized_fields(self) -> None:
        """Validate serialized blobs on every write path, not only ``create_filter``.

        Raw ORM create/write (server code, data files, future RPC) must validate
        too so the IRF-L1 guarantee holds at the write boundary (IRF-L2).
        """
        for filter_ in self:
            self._validate_serialized_fields(
                {
                    "domain": filter_.domain,
                    "context": filter_.context,
                    "sort": filter_.sort,
                }
            )

    @api.model
    def create_filter(self, vals: dict[str, Any]) -> Self:
        embedded_action_id = vals.get("embedded_action_id")
        if not embedded_action_id and "embedded_parent_res_id" in vals:
            del vals["embedded_parent_res_id"]
        # _validate_serialized_fields raises ValidationError before the DB hit,
        # preserving the contract the RPC tests assert; the @api.constrains
        # backstop (IRF-L2) re-validates on the underlying create anyway.
        self._validate_serialized_fields(vals)
        return self.create(vals)

    @api.model
    def _list_all_models(self) -> list[tuple[str, str]]:
        lang = self.env.lang or "en_US"
        # The ::text cast is required: psycopg3 cannot infer the parameter type
        # for the jsonb->>'key' operator when the key is a bound parameter.
        self.env.cr.execute(
            SQL(
                "SELECT model, COALESCE(name->>(%s::text), name->>'en_US') FROM ir_model ORDER BY 2",
                lang,
            )
        )
        return self.env.cr.fetchall()

    def copy_data(self, default: ValuesType | None = None) -> list[ValuesType]:
        vals_list = super().copy_data(default=default)
        # A NULL Integer reads as 0, which would trigger
        # check_res_id_only_when_embedded_action here.
        for vals in vals_list:
            if vals.get("embedded_parent_res_id") == 0:
                del vals["embedded_parent_res_id"]
        return [
            dict(vals, name=self.env._("%s (copy)", ir_filter.name))
            for ir_filter, vals in zip(self, vals_list, strict=True)
        ]

    def _get_eval_domain(self) -> list:
        try:
            return ast.literal_eval(self.domain)
        except (ValueError, SyntaxError) as e:
            raise ValueError(f"Invalid domain: {self.domain}") from e

    @api.model
    def _get_action_domain(
        self,
        action_id: int | None = None,
        embedded_action_id: int | None = None,
        embedded_parent_res_id: int | None = None,
    ) -> list[tuple]:
        """Return a domain component for matching filters that are visible in the
        same context (menu/view) as the given action."""
        action_condition = (
            ("action_id", "in", [action_id, False])
            if action_id
            else ("action_id", "=", False)
        )
        embedded_condition = (
            ("embedded_action_id", "=", embedded_action_id)
            if embedded_action_id
            else ("embedded_action_id", "=", False)
        )
        embedded_parent_res_id_condition = (
            ("embedded_parent_res_id", "=", embedded_parent_res_id)
            if embedded_action_id and embedded_parent_res_id
            else ("embedded_parent_res_id", "in", [0, False])
        )

        return [
            action_condition,
            embedded_condition,
            embedded_parent_res_id_condition,
        ]

    @api.model
    def get_filters(
        self,
        model: str,
        action_id: int | None = None,
        embedded_action_id: int | None = None,
        embedded_parent_res_id: int | None = None,
    ) -> list[ValuesType]:
        """Return the filters available to the current user on the given model.

        :param str model: the ``model_id`` value (e.g. ``"res.partner"``), not a db id.
        :param action_id: if set, restrict to this action plus global filters;
            otherwise only global filters. The action need not match the model.
        :param embedded_action_id: embedded action the filter is scoped to;
            combined with ``embedded_parent_res_id``.
        :param embedded_parent_res_id: parent record the embedded-action filter
            applies to; only meaningful with ``embedded_action_id``.
        :return: list of dicts with ``name``, ``is_default``, ``domain``,
            ``context``, ``user_ids``, ``sort``, ``embedded_action_id`` and
            ``embedded_parent_res_id``.
        :rtype: list[dict]
        """
        # available filters: private filters (user_ids=uids) and public filters (uids=NULL),
        # and filters for the action (action_id=action_id) or global (action_id=NULL)
        user_context = self.env["res.users"].context_get()
        action_domain = self._get_action_domain(
            action_id, embedded_action_id, embedded_parent_res_id
        )
        return self.with_context(user_context).search_read(
            action_domain
            + [
                ("model_id", "=", model),
                ("user_ids", "in", [self.env.uid, False]),
            ],
            [
                "name",
                "is_default",
                "domain",
                "context",
                "user_ids",
                "sort",
                "embedded_action_id",
                "embedded_parent_res_id",
            ],
        )

    @api.model
    def _validate_serialized_fields(self, vals: dict[str, Any]) -> None:
        """Validate that stored ``domain``/``context``/``sort`` blobs have the right shape.

        These are persisted as free-form text that downstream consumers evaluate.
        A malformed favorite created over RPC would break the favorites dropdown
        for everyone sharing it, failing far from its cause; validate at the
        write boundary instead.

        :param dict vals: filter values about to be persisted.
        :raises ValidationError: if ``domain`` is not a list, ``context`` is not a
            dict, or ``sort`` is not a list of strings.
        """
        for fname, types, label in (
            ("domain", (list, tuple), "list"),
            ("context", (dict,), "dict"),
            ("sort", (list, tuple), "list"),
        ):
            raw = vals.get(fname)
            if raw is None or isinstance(raw, types):
                parsed = raw
            elif not isinstance(raw, str):
                raise ValidationError(
                    self.env._(
                        "Filter %(field)s must be a %(type)s.", field=fname, type=label
                    )
                )
            else:
                try:
                    parsed = ast.literal_eval(raw)
                except (ValueError, SyntaxError) as e:
                    raise ValidationError(
                        self.env._(
                            "Invalid filter %(field)s: %(error)s", field=fname, error=e
                        )
                    ) from e
                if not isinstance(parsed, types):
                    raise ValidationError(
                        self.env._(
                            "Filter %(field)s must be a %(type)s.",
                            field=fname,
                            type=label,
                        )
                    )
            # The DB CHECK on `sort` only enforces "jsonb array"; it accepts
            # non-string elements (e.g. [1, 2]) that blow up later at
            # ",".join(...). Enforce list-of-strings here (IRF-C1).
            if fname == "sort" and parsed is not None:
                if not all(isinstance(item, str) for item in parsed):
                    raise ValidationError(
                        self.env._("Filter sort must be a list of strings.")
                    )
