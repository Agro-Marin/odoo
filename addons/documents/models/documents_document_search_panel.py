"""The search panel's folder tree, and the "Recent" grouping behind it.

Presentation only: what the client is handed to draw the left-hand tree,
plus the per-partner last-access bucketing that backs "Recent" and its
group-by. None of it decides access; it renders what access allows.
"""

from collections import OrderedDict
from typing import Any

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.fields import Domain
from odoo.tools import SQL

from odoo.addons.documents.tools import UserFolder


class DocumentsDocument(models.Model):
    _inherit = "documents.document"

    def _search_last_access_date_group(
        self, operator: str, operand: list | set
    ) -> list:
        if operator != "in":
            return NotImplemented
        values = set(operand)
        if False in values:
            query = SQL(
                "(%s SELECT document_id FROM last_access_date)",
                self._get_last_access_date_group_cte(),
            )
            no_access_date = [("id", "not in", query)]
            if len(values) > 1:
                values.remove(False)
                # "in [False, X, ...]" means "no access date" OR "in one of the
                # X groups" -- the two leaves must be OR-ed, not AND-ed.
                return [
                    "|",
                    *no_access_date,
                    *self._search_last_access_date_group(operator, values),
                ]
            return no_access_date
        query = SQL(
            """(%s SELECT document_id FROM last_access_date WHERE date = ANY(%s))""",
            self._get_last_access_date_group_cte(),
            list(values),
        )
        return [("id", "in", query)]

    # The CTE buckets on `access_ids.last_access_date`, and it filters on the
    # *current* user's partner, so the result is both value- and user-dependent.
    @api.depends("access_ids", "access_ids.last_access_date")
    @api.depends_context("uid")
    def _compute_last_access_date_group(self) -> None:
        # Raw SQL: pending ORM writes on the bucketed column would otherwise be
        # invisible and the compute would report the pre-write bucket.
        self.env["documents.access"].flush_model(["last_access_date"])
        self.env.cr.execute(
            SQL(
                """(%s SELECT document_id, date FROM last_access_date WHERE document_id = ANY(%s))""",
                self._get_last_access_date_group_cte(),
                self.ids,
            )
        )
        values = {
            line["document_id"]: line["date"] for line in self.env.cr.dictfetchall()
        }
        for document in self:
            document.last_access_date_group = values.get(document.id)

    def _field_to_sql(self, alias: str, fname: str, query: Any = None) -> SQL:
        """Render *fname* as SQL, joining the per-partner access dates on demand.

        ``last_access_date_group`` resolves through a LEFT JOIN rather than a
        correlated subquery so the expression can be grouped on: PostgreSQL 18
        rejects a correlated subquery referencing ungrouped outer columns.

        The join therefore has to be added to a *query*, and without one there
        is nothing to add it to. Returning the alias anyway produced SQL
        referencing a join that was never made -- a syntax error at execution,
        blamed on whatever assembled the statement rather than on the caller
        that omitted the query.

        :raise ValueError: for ``last_access_date_group`` without a *query*
        """
        if fname == "last_access_date_group":
            if query is None:
                msg = (
                    "last_access_date_group needs a query to hang its join on; "
                    "it cannot be rendered as a standalone expression"
                )
                raise ValueError(msg)
            join_alias = f"{alias}__last_access"
            subquery = SQL(
                """(SELECT document_id,
                    %s AS date_group
                    FROM documents_access
                    WHERE partner_id = %s)""",
                self._last_access_date_group_case_sql(),
                self.env.user.partner_id.id,
            )
            condition = SQL(
                "%s = %s",
                SQL.identifier(join_alias, "document_id"),
                SQL.identifier(alias, "id"),
            )
            query.add_join("LEFT JOIN", join_alias, subquery, condition)
            return SQL.identifier(join_alias, "date_group")

        return super()._field_to_sql(alias, fname, query)

    def _get_last_access_date_group_cte(self) -> SQL:
        return SQL(
            """
            WITH last_access_date AS (
                SELECT %s AS date,
                       document_id
                  FROM documents_access
                 WHERE partner_id = %s
            )
        """,
            self._last_access_date_group_case_sql(),
            self.env.user.partner_id.id,
        )

    @api.model
    def _get_search_panel_fields(self) -> list:
        """Return the list of fields used by the search panel."""
        search_panel_fields = [
            "access_internal",
            "access_token",
            "access_via_link",
            "active",
            "company_id",
            "description",
            "display_name",
            "user_folder_id",
            "is_access_via_link_hidden",
            "is_favorited",
            "mail_alias_domain_count",
            "owner_id",
            "shortcut_document_id",
            "user_permission",
        ]
        if not self.env.user.share:
            search_panel_fields += [
                "alias_domain_id",
                "alias_email",
                "alias_name",
                "alias_tag_ids",
                "create_activity_type_id",
                "create_activity_user_id",
                "partner_id",
            ]
        return search_panel_fields

    def _last_access_date_group_case_sql(self) -> SQL:
        """CASE bucketing ``documents_access.last_access_date`` into the UI groups.

        The cutoffs are computed in Python (``fields.Datetime.now()``, naive UTC)
        and passed as parameters rather than using SQL ``NOW() - INTERVAL``: the
        column stores naive UTC, whereas ``NOW()`` on a ``timestamp`` column
        resolves in the database session's timezone, so the two only agree when
        that session runs in UTC. Python cutoffs make the bucketing consistent
        with the ORM clock and deterministic under ``freeze_time``. This is the
        single source shared by the compute, the search and the group-by SQL.
        """
        now = fields.Datetime.now()
        return SQL(
            """(CASE
                   WHEN last_access_date > %s THEN '3_day'
                   WHEN last_access_date > %s THEN '2_week'
                   WHEN last_access_date > %s THEN '1_month'
                   ELSE '0_older'
               END)""",
            now - relativedelta(days=1),
            now - relativedelta(days=7),
            now - relativedelta(months=1),
        )

    def _order_field_to_sql(
        self, alias: str, field_name: str, direction: SQL, nulls: SQL, query: Any
    ) -> SQL:
        if field_name == "last_access_date_group":
            sql_field = SQL(
                "SELECT last_access_date FROM documents_access WHERE partner_id = %s AND document_id = %s",
                self.env.user.partner_id.id,
                SQL.identifier(alias, "id"),
            )
            return SQL("(%s) %s %s", sql_field, direction, nulls)

        if field_name == "is_folder":
            sql_field = SQL("%s != 'folder'", SQL.identifier(alias, "type"))
            return SQL("(%s) %s %s", sql_field, direction, nulls)

        return super()._order_field_to_sql(alias, field_name, direction, nulls, query)

    @api.model
    def _search_panel_folder_counts(self, model_domain: Domain) -> dict:
        """Count the documents each folder directly holds, for the search panel.

        The generic counter machinery (`_search_panel_domain_image`) can only
        group on a *stored* many2one/selection: fed ``user_folder_id`` -- a
        non-stored computed Char -- it took its "selection field" branch and
        died on ``KeyError: 'selection'``, so ``enable_counters`` was a hard 500
        on this search panel rather than a supported option. The virtual field
        is only a presentation of the stored ``folder_id``, so count on that.

        :return: ``{folder_id: number of matching documents directly inside}``
        """
        return {
            folder.id: count
            for folder, count in self._read_group(
                model_domain & Domain("folder_id", "!=", False),
                groupby=["folder_id"],
                aggregates=["__count"],
            )
        }

    @api.model
    def _search_panel_rollup_folder_counts(self, values_range: dict) -> None:
        """Add each folder's descendant counts to its ancestors, in place.

        `_search_panel_global_counters` walks the ``user_folder_id`` chain, but
        that chain leaves ``values_range`` as soon as a folder sits under a
        virtual root ("MY", "COMPANY", "SHARED"), which is a *string* key it
        would then look up and ``KeyError`` on. Walk the stored ``folder_id``
        chain instead: it is an id or ``False``, and it terminates naturally.
        """
        parent_by_folder = {
            folder.id: folder.folder_id.id for folder in self.browse(values_range)
        }
        local_counts = {
            folder_id: values["__count"] for folder_id, values in values_range.items()
        }
        for folder_id, count in local_counts.items():
            if not count:
                continue
            seen = {folder_id}
            parent_id = parent_by_folder.get(folder_id)
            # `seen` guards against a parent cycle, which the DB does not
            # prevent across several rows (only `folder_id <> id` is enforced).
            while parent_id and parent_id not in seen:
                seen.add(parent_id)
                if parent_id in values_range:
                    values_range[parent_id]["__count"] += count
                parent_id = parent_by_folder.get(parent_id)

    @api.model
    def search_panel_select_range(self, field_name: str, **kwargs) -> dict:
        """Return the search panel range values, with virtual folder roots."""

        def convert_user_folder_ids_to_int(vals: dict) -> None:
            """Key the category tree on the parent's id where there is one.

            The client matches a node's parent by *id*, so a real folder has to
            come back as an ``int`` while the virtual roots stay strings.
            """
            user_folder = self._parse_user_folder(vals["user_folder_id"])
            if user_folder is not None and user_folder.is_folder:
                vals["user_folder_id"] = user_folder.folder_id

        if field_name == "user_folder_id":
            enable_counters = kwargs.get("enable_counters", False)
            search_panel_fields = self._get_search_panel_fields()
            domain = Domain("type", "=", "folder")

            if unique_folder_id := self.env.context.get("documents_unique_folder_id"):
                values = self.env["documents.document"].search_read(
                    domain & Domain("folder_id", "child_of", unique_folder_id),
                    search_panel_fields,
                )
                for record in values:
                    convert_user_folder_ids_to_int(record)
                    if record["id"] == unique_folder_id:
                        record["user_folder_id"] = False  # Set as root
                return {
                    "parent_field": "user_folder_id",
                    "values": values,
                }

            records = self.env["documents.document"].search_read(
                domain, search_panel_fields
            )
            alias_tag_data = {}
            if not self.env.user.share:
                alias_tag_ids = {
                    alias_tag_id
                    for rec in records
                    for alias_tag_id in rec["alias_tag_ids"]
                }
                alias_tag_data = {
                    alias_tag["id"]: {
                        "id": alias_tag.id,
                        "color": alias_tag.color,
                        "display_name": alias_tag.display_name,
                    }
                    for alias_tag in self.env["documents.tag"].browse(alias_tag_ids)
                }
            local_counts = {}
            if enable_counters:
                model_domain = Domain.AND(
                    [
                        kwargs.get("search_domain", []),
                        kwargs.get("category_domain", []),
                        kwargs.get("filter_domain", []),
                    ]
                )
                local_counts = self._search_panel_folder_counts(model_domain)

            # Read the targets in batch
            targets = self.browse(
                r["shortcut_document_id"][0]
                for r in records
                if r["shortcut_document_id"]
            )
            targets_user_permission = {t.id: t.user_permission for t in targets}

            values_range = OrderedDict()
            for record in records:
                record_id = record["id"]
                convert_user_folder_ids_to_int(record)
                if not self.env.user.share:
                    record["alias_tag_ids"] = [
                        alias_tag_data[tag_id] for tag_id in record["alias_tag_ids"]
                    ]
                if enable_counters:
                    record["__count"] = local_counts.get(record_id, 0)
                if record["shortcut_document_id"]:
                    record["target_user_permission"] = targets_user_permission[
                        record["shortcut_document_id"][0]
                    ]
                values_range[record_id] = record

            if enable_counters:
                self._search_panel_rollup_folder_counts(values_range)

            special_roots = []
            if not self.env.user.share:
                special_roots = [
                    {
                        "bold": True,
                        "childrenIds": [],
                        "parentId": False,
                        "user_permission": "edit",
                    }
                    | values
                    for values in [
                        {
                            "display_name": _("Company"),
                            "id": UserFolder.COMPANY,
                            "description": _("Common roots for all company users."),
                            "user_permission": "edit"
                            if self.env.user.has_group(
                                "documents.group_documents_manager"
                            )
                            else "view",
                        },
                        {
                            "display_name": _("My Drive"),
                            "id": UserFolder.MY,
                            "user_permission": "edit",
                            "description": _("Your individual space."),
                        },
                        {
                            "display_name": _("Shared with me"),
                            "id": UserFolder.SHARED,
                            "description": _(
                                "Additional documents you have access to."
                            ),
                        },
                        {
                            "display_name": _("Recent"),
                            "id": UserFolder.RECENT,
                            "description": _("Recently accessed documents."),
                        },
                    ]
                ]
                if not self.env.context.get("documents_search_panel_no_trash"):
                    special_roots.append(
                        {
                            "display_name": _("Trash"),
                            "id": UserFolder.TRASH,
                            "description": _(
                                "Items in trash will be deleted forever after %s days.",
                                self.get_deletion_delay(),
                            ),
                        }
                    )

            return {
                "parent_field": "user_folder_id",
                "values": list(values_range.values()) + special_roots,
            }

        return super().search_panel_select_range(field_name, **kwargs)
