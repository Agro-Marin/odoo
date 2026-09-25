from unittest.mock import patch

from odoo.db import schema
from odoo.libs.sql import SQL
from odoo.tests.common import TransactionCase
from odoo.tools import frozendict

_PARTNER_QUERY = SQL(
    """
    SELECT p.id, p.name, u.id AS user_id
    FROM res_partner p
    JOIN res_users u ON u.partner_id = p.id
    JOIN res_groups_users_rel r ON r.uid = u.id
    WHERE p.active
    """
)


class TestViewColumnReads(TransactionCase):
    def test_a_view_lists_every_column_it_reads(self):
        cr = self.env.cr
        cr.execute("CREATE TEMP TABLE _vr_a (id int, x int, y int, z int)")
        cr.execute("CREATE TEMP TABLE _vr_b (id int, a_id int)")
        cr.execute(
            "CREATE TEMP VIEW _vr_v AS SELECT _vr_a.x, count(*) AS n FROM _vr_a "
            "JOIN _vr_b ON _vr_b.a_id = _vr_a.id WHERE _vr_a.y > 0 GROUP BY _vr_a.x"
        )
        cr.execute("CREATE TEMP VIEW _vr_w AS SELECT n FROM _vr_v")
        cr.execute("CREATE TEMP VIEW _vr_count AS SELECT count(*) FROM _vr_b")
        reads = schema.get_view_column_reads(
            cr, ["_vr_v", "_vr_w", "_vr_count", "_vr_a", "_vr_missing"]
        )
        self.assertEqual(
            reads,
            {
                "_vr_v": {
                    ("_vr_a", "id"),
                    ("_vr_a", "x"),
                    ("_vr_a", "y"),
                    ("_vr_b", "a_id"),
                },
                "_vr_w": {("_vr_v", "n")},
            },
        )


class TestUndeclaredViewReads(TransactionCase):
    def setUp(self):
        super().setUp()
        self.model_cls = self.registry["res.users.apikeys"]

    def _undeclared(self, table_query, depends=frozendict()):
        with (
            patch.object(self.model_cls, "_table_query", table_query),
            patch.object(self.model_cls, "_depends", depends),
        ):
            return self.registry.get_undeclared_view_reads(
                self.env.cr, ["res.users.apikeys"]
            )

    def test_a_query_without_depends_reports_every_stored_column_it_reads(self):
        undeclared = self._undeclared(_PARTNER_QUERY)["res.users.apikeys"]
        self.assertEqual(
            set(undeclared),
            {
                "res.partner.name",
                "res.partner.active",
                "res.users.partner_id",
                "res.groups.user_ids",
            },
        )

    def test_depends_naming_every_read_leaves_nothing(self):
        depends = frozendict(
            {
                "res.partner": ["name", "active"],
                "res.users": ["partner_id", "group_ids"],
            }
        )
        self.assertEqual(self._undeclared(_PARTNER_QUERY, depends), {})

    def test_a_field_reached_through_another_models_depends_counts(self):
        with patch.object(
            type(self.env["res.users"]),
            "_depends",
            frozendict({"res.partner": ["name", "active"]}),
        ):
            undeclared = self._undeclared(
                _PARTNER_QUERY,
                frozendict({"res.users": ["partner_id", "group_ids"]}),
            )
        self.assertEqual(undeclared, {})

    def test_a_field_the_query_flushes_itself_counts(self):
        name = self.env["res.partner"]._fields["name"]
        query = SQL(
            "SELECT p.id, %s FROM res_partner p",
            SQL.identifier("p", "name", to_flush=name),
        )
        self.assertEqual(self._undeclared(query), {})

    def test_a_view_named_by_its_table_is_read_from_the_catalog(self):
        self.env.cr.execute(
            "CREATE TEMP VIEW _vr_apikeys AS SELECT id, login FROM res_users"
        )
        with (
            patch.object(self.model_cls, "_table", "_vr_apikeys"),
            patch.object(self.model_cls, "_table_query", None),
        ):
            undeclared = self.registry.get_undeclared_view_reads(
                self.env.cr, ["res.users.apikeys"]
            )
        self.assertEqual(undeclared, {"res.users.apikeys": ["res.users.login"]})

    def test_a_stale_read_is_what_it_reports(self):
        partner = self.env["res.partner"].create({"name": "Before"})
        self.env.flush_all()
        partner.name = "After"
        query = SQL("SELECT id, name FROM res_partner WHERE id = %s", partner.id)
        apikeys = self.env["res.users.apikeys"]
        with (
            patch.object(self.model_cls, "_table_query", query),
            patch.object(self.model_cls, "_depends", frozendict()),
        ):
            self.assertEqual(
                apikeys.search_fetch([], ["name"]).mapped("name"), ["Before"]
            )
        self.env.invalidate_all()
        partner.name = "After again"
        with (
            patch.object(self.model_cls, "_table_query", query),
            patch.object(
                self.model_cls, "_depends", frozendict({"res.partner": ["name"]})
            ),
        ):
            self.assertEqual(
                apikeys.search_fetch([], ["name"]).mapped("name"), ["After again"]
            )

    def test_install_warns_about_an_undeclared_read(self):
        with (
            patch.object(self.model_cls, "_table_query", _PARTNER_QUERY),
            patch.object(self.model_cls, "_depends", frozendict()),
            self.assertLogs("odoo.schema", "WARNING") as logs,
        ):
            self.registry.check_view_depends(self.env.cr, ["res.users.apikeys"])
        self.assertIn("res.users.apikeys", logs.output[0])
        self.assertIn("res.partner.name", logs.output[0])
