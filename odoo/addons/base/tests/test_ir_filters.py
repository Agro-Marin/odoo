import ast
import logging

import psycopg.errors

from odoo.exceptions import ValidationError
from odoo.tests.common import ADMIN_USER_ID, TransactionCase, tagged
from odoo.tools import mute_logger

from odoo.addons.base.models.ir_actions import eval_action_context
from odoo.addons.base.tests.common import TransactionCaseWithUserDemo

_logger = logging.getLogger(__name__)


def noid(seq):
    for d in seq:
        d.pop("id", None)
        d.pop("action_id", None)
        d.pop("embedded_action_id", None)
        d.pop("embedded_parent_res_id", None)
    return seq


class FiltersCase(TransactionCaseWithUserDemo):
    def setUp(self):
        super().setUp()
        self.USER_NG = self.env["res.users"].name_search("demo")[0]
        self.USER_ID = self.USER_NG[0]

    def build(self, model, *args):
        Model = self.env[model].with_user(ADMIN_USER_ID)
        Model.create(args)


class TestGetFilters(FiltersCase):
    def test_own_filters(self):
        self.build(
            "ir.filters",
            {"name": "a", "user_ids": [self.USER_ID], "model_id": "ir.filters"},
            {"name": "b", "user_ids": [self.USER_ID], "model_id": "ir.filters"},
            {"name": "c", "user_ids": [self.USER_ID], "model_id": "ir.filters"},
            {"name": "d", "user_ids": [self.USER_ID], "model_id": "ir.filters"},
        )

        filters = (
            self.env["ir.filters"].with_user(self.USER_ID).get_filters("ir.filters")
        )

        self.assertItemsEqual(
            noid(filters),
            [
                {
                    "name": "a",
                    "is_default": False,
                    "user_ids": [self.USER_NG[0]],
                    "domain": "[]",
                    "context": "{}",
                    "sort": "[]",
                },
                {
                    "name": "b",
                    "is_default": False,
                    "user_ids": [self.USER_NG[0]],
                    "domain": "[]",
                    "context": "{}",
                    "sort": "[]",
                },
                {
                    "name": "c",
                    "is_default": False,
                    "user_ids": [self.USER_NG[0]],
                    "domain": "[]",
                    "context": "{}",
                    "sort": "[]",
                },
                {
                    "name": "d",
                    "is_default": False,
                    "user_ids": [self.USER_NG[0]],
                    "domain": "[]",
                    "context": "{}",
                    "sort": "[]",
                },
            ],
        )

    def test_global_filters(self):
        self.build(
            "ir.filters",
            {"name": "a", "user_ids": [], "model_id": "ir.filters"},
            {"name": "b", "user_ids": [], "model_id": "ir.filters"},
            {"name": "c", "user_ids": [], "model_id": "ir.filters"},
            {"name": "d", "user_ids": [], "model_id": "ir.filters"},
        )

        filters = (
            self.env["ir.filters"].with_user(self.USER_ID).get_filters("ir.filters")
        )

        self.assertItemsEqual(
            noid(filters),
            [
                {
                    "name": "a",
                    "is_default": False,
                    "user_ids": [],
                    "domain": "[]",
                    "context": "{}",
                    "sort": "[]",
                },
                {
                    "name": "b",
                    "is_default": False,
                    "user_ids": [],
                    "domain": "[]",
                    "context": "{}",
                    "sort": "[]",
                },
                {
                    "name": "c",
                    "is_default": False,
                    "user_ids": [],
                    "domain": "[]",
                    "context": "{}",
                    "sort": "[]",
                },
                {
                    "name": "d",
                    "is_default": False,
                    "user_ids": [],
                    "domain": "[]",
                    "context": "{}",
                    "sort": "[]",
                },
            ],
        )

    def test_no_third_party_filters(self):
        self.build(
            "ir.filters",
            {"name": "a", "user_ids": [], "model_id": "ir.filters"},
            {
                "name": "b",
                "user_ids": [ADMIN_USER_ID],
                "model_id": "ir.filters",
            },
            {"name": "c", "user_ids": [self.USER_ID], "model_id": "ir.filters"},
            {
                "name": "d",
                "user_ids": [ADMIN_USER_ID],
                "model_id": "ir.filters",
            },
        )

        filters = (
            self.env["ir.filters"].with_user(self.USER_ID).get_filters("ir.filters")
        )

        self.assertItemsEqual(
            noid(filters),
            [
                {
                    "name": "a",
                    "is_default": False,
                    "user_ids": [],
                    "domain": "[]",
                    "context": "{}",
                    "sort": "[]",
                },
                {
                    "name": "c",
                    "is_default": False,
                    "user_ids": [self.USER_NG[0]],
                    "domain": "[]",
                    "context": "{}",
                    "sort": "[]",
                },
            ],
        )


@tagged("post_install", "-at_install", "migration")
class TestAllFilters(TransactionCase):
    def check_filter(self, name, model, domain, aggregates, groupby, order, context):
        if groupby:
            try:
                Model = self.env[model].with_context(context)
                groupby = [groupby] if isinstance(groupby, str) else groupby
                groupby = [
                    (
                        f"{group_spec}:month"
                        if (
                            ":" not in group_spec
                            and group_spec in Model._fields
                            and Model._fields[group_spec].type in ("date, datetime")
                        )
                        else group_spec
                    )
                    for group_spec in groupby
                ]
                Model.formatted_read_group(domain, groupby, aggregates, order=order)
            except ValueError as e:
                raise self.failureException(
                    "Test filter '%s' failed: %s" % (name, e)
                ) from None
            except KeyError as e:
                raise self.failureException(
                    "Test filter '%s' failed: field or aggregate %s does not exist"
                    % (name, e)
                ) from None
        elif domain:
            try:
                self.env[model].with_context(context).search(domain, order=order)
            except ValueError as e:
                raise self.failureException(
                    "Test filter '%s' failed: %s" % (name, e)
                ) from None
        else:
            _logger.info(
                "No domain or group by in filter %s with model %s and context %s",
                name,
                model,
                context,
            )

    def test_filters(self):
        for filter_ in self.env["ir.filters"].search([]):
            with self.subTest(name=filter_.name):
                context = eval_action_context(filter_.context, self.env)
                groupby = context.get("group_by")
                self.check_filter(
                    name=filter_.name,
                    model=filter_.model_id,
                    domain=filter_._get_eval_domain(),
                    aggregates=["__count"],
                    groupby=groupby,
                    order=",".join(ast.literal_eval(filter_.sort)),
                    context=context,
                )


class TestEmbeddedFilters(FiltersCase):
    def setUp(self):
        super().setUp()
        self.USER_NG = self.env["res.users"].name_search("demo")[0]
        self.USER_ID = self.USER_NG[0]
        self.parent_action = self.env["ir.actions.act_window"].create(
            {
                "name": "ParentAction",
                "res_model": "res.partner",
            }
        )
        self.action_1 = self.env["ir.actions.act_window"].create(
            {
                "name": "Action1",
                "res_model": "res.partner",
            }
        )
        self.embedded_action_1 = self.env["ir.embedded.actions"].create(
            {
                "name": "EmbeddedAction1",
                "parent_res_model": "res.partner",
                "parent_action_id": self.parent_action.id,
                "action_id": self.action_1.id,
            }
        )
        self.embedded_action_2 = self.env["ir.embedded.actions"].create(
            {
                "name": "EmbeddedAction2",
                "parent_res_model": "res.partner",
                "parent_action_id": self.parent_action.id,
                "action_id": self.action_1.id,
            }
        )

    def test_global_filters_with_embedded_action(self):
        Filters = self.env["ir.filters"].with_user(self.USER_ID)
        Filters.create_filter(
            {
                "name": "a",
                "model_id": "ir.filters",
                "user_ids": [],
                "is_default": True,
                "embedded_action_id": self.embedded_action_1.id,
                "embedded_parent_res_id": 1,
            }
        )
        Filters.create_filter(
            {
                "name": "b",
                "model_id": "ir.filters",
                "user_ids": [self.USER_ID],
                "is_default": False,
                "embedded_action_id": self.embedded_action_2.id,
                "embedded_parent_res_id": 1,
            }
        )

        filters = (
            self.env["ir.filters"]
            .with_user(self.USER_ID)
            .get_filters(
                "ir.filters",
                embedded_action_id=self.embedded_action_1.id,
                embedded_parent_res_id=1,
            )
        )
        self.assertItemsEqual(
            noid(filters),
            [
                {
                    "name": "a",
                    "is_default": True,
                    "user_ids": [],
                    "domain": "[]",
                    "context": "{}",
                    "sort": "[]",
                }
            ],
        )

        filters = (
            self.env["ir.filters"]
            .with_user(self.USER_ID)
            .get_filters(
                "ir.filters",
                embedded_action_id=self.embedded_action_1.id,
                embedded_parent_res_id=2,
            )
        )
        self.assertItemsEqual(noid(filters), [])

        filters = (
            self.env["ir.filters"]
            .with_user(ADMIN_USER_ID)
            .get_filters(
                "ir.filters",
                embedded_action_id=self.embedded_action_1.id,
                embedded_parent_res_id=1,
            )
        )
        self.assertItemsEqual(
            noid(filters),
            [
                {
                    "name": "a",
                    "is_default": True,
                    "user_ids": [],
                    "domain": "[]",
                    "context": "{}",
                    "sort": "[]",
                }
            ],
        )

        filters = (
            self.env["ir.filters"].with_user(self.USER_ID).get_filters("ir.filters")
        )
        self.assertItemsEqual(noid(filters), [])

    def test_global_filters_with_no_embedded_action(self):
        Filters = self.env["ir.filters"].with_user(self.USER_ID)
        filter_a = Filters.create_filter(
            {
                "name": "a",
                "model_id": "ir.filters",
                "user_ids": [],
                "is_default": True,
                "embedded_action_id": False,
                "embedded_parent_res_id": 0,
            }
        )
        filter_b = Filters.create_filter(
            {
                "name": "b",
                "model_id": "ir.filters",
                "user_ids": [self.USER_ID],
                "is_default": True,
                "embedded_action_id": False,
                "embedded_parent_res_id": 1,
            }
        )
        self.assertFalse(filter_a.embedded_action_id)
        self.assertFalse(filter_a.embedded_parent_res_id)
        self.assertFalse(filter_b.embedded_action_id)
        self.assertFalse(filter_b.embedded_parent_res_id)


@tagged("post_install", "-at_install")
class TestCreateFilterValidation(FiltersCase):
    def test_create_filter_rejects_non_list_domain(self):
        with self.assertRaises(ValidationError):
            self.env["ir.filters"].create_filter(
                {
                    "name": "bad domain",
                    "model_id": "res.partner",
                    "domain": "{'a': 1}",
                    "context": "{}",
                }
            )

    def test_create_filter_rejects_non_dict_context(self):
        with self.assertRaises(ValidationError):
            self.env["ir.filters"].create_filter(
                {
                    "name": "bad context",
                    "model_id": "res.partner",
                    "domain": "[]",
                    "context": "[1, 2]",
                }
            )

    def test_create_filter_rejects_unparseable_domain(self):
        with self.assertRaises(ValidationError):
            self.env["ir.filters"].create_filter(
                {
                    "name": "broken",
                    "model_id": "res.partner",
                    "domain": "[('a', '=',",
                    "context": "{}",
                }
            )

    def test_create_filter_accepts_valid(self):
        ir_filter = self.env["ir.filters"].create_filter(
            {
                "name": "good filter",
                "model_id": "res.partner",
                "domain": "[('is_company', '=', True)]",
                "context": "{'group_by': ['country_id']}",
            }
        )
        self.assertTrue(ir_filter)
        self.assertEqual(ir_filter._get_eval_domain(), [("is_company", "=", True)])


@tagged("post_install", "-at_install")
class TestConstrainsValidation(FiltersCase):
    def test_raw_create_rejects_non_list_domain(self):
        with self.assertRaises(ValidationError):
            self.env["ir.filters"].create(
                {
                    "name": "raw bad domain",
                    "model_id": "res.partner",
                    "domain": "{'a': 1}",
                    "context": "{}",
                }
            )

    def test_raw_create_rejects_non_dict_context(self):
        with self.assertRaises(ValidationError):
            self.env["ir.filters"].create(
                {
                    "name": "raw bad context",
                    "model_id": "res.partner",
                    "domain": "[]",
                    "context": "[1, 2]",
                }
            )

    def test_raw_write_rejects_malformed_domain(self):
        ir_filter = self.env["ir.filters"].create(
            {"name": "ok", "model_id": "res.partner"}
        )
        with self.assertRaises(ValidationError):
            ir_filter.write({"domain": "{'a': 1}"})

    def test_create_rejects_sort_with_non_string_elements(self):
        with self.assertRaises(ValidationError):
            self.env["ir.filters"].create(
                {
                    "name": "bad sort",
                    "model_id": "res.partner",
                    "sort": "[1, 2]",
                }
            )

    def test_create_filter_rejects_sort_with_non_string_elements(self):
        with self.assertRaises(ValidationError):
            self.env["ir.filters"].create_filter(
                {
                    "name": "bad sort rpc",
                    "model_id": "res.partner",
                    "sort": "[1, 2]",
                }
            )

    def test_create_accepts_sort_list_of_strings(self):
        ir_filter = self.env["ir.filters"].create(
            {
                "name": "good sort",
                "model_id": "res.partner",
                "sort": '["name desc", "id"]',
            }
        )
        self.assertTrue(ir_filter)


@tagged("post_install", "-at_install")
class TestDynamicDomainValidation(FiltersCase):
    DYNAMIC_UID_DOMAIN = '[("create_uid", "=", uid)]'
    DYNAMIC_DATE_DOMAIN = (
        '[("activity_date", ">=", '
        '(context_today() - datetime.timedelta(days = 30)).strftime("%Y-%m-%d"))]'
    )

    def _create_dynamic(self, domain):
        return self.env["ir.filters"].create(
            {"name": "dynamic", "model_id": "res.partner", "domain": domain}
        )

    def test_create_filter_accepts_dynamic_uid_domain(self):
        ir_filter = self.env["ir.filters"].create_filter(
            {
                "name": "My Document(s)",
                "model_id": "ir.attachment",
                "domain": self.DYNAMIC_UID_DOMAIN,
                "context": "{}",
            }
        )
        self.assertEqual(ir_filter.domain, self.DYNAMIC_UID_DOMAIN)

    def test_create_filter_accepts_dynamic_date_domain(self):
        ir_filter = self.env["ir.filters"].create_filter(
            {
                "name": "Late Activities",
                "model_id": "res.partner",
                "domain": self.DYNAMIC_DATE_DOMAIN,
                "context": "{}",
            }
        )
        self.assertEqual(ir_filter.domain, self.DYNAMIC_DATE_DOMAIN)

    def test_copy_dynamic_row_succeeds(self):
        ir_filter = self._create_dynamic(self.DYNAMIC_UID_DOMAIN)
        copied = ir_filter.copy()
        self.assertEqual(copied.domain, self.DYNAMIC_UID_DOMAIN)

    def test_write_sort_on_dynamic_row_succeeds(self):
        ir_filter = self._create_dynamic(self.DYNAMIC_DATE_DOMAIN)
        ir_filter.write({"sort": '["name desc"]'})
        self.assertEqual(ir_filter.sort, '["name desc"]')

    def test_write_unvalidated_fields_on_dynamic_row_succeeds(self):
        ir_filter = self._create_dynamic(self.DYNAMIC_UID_DOMAIN)
        ir_filter.write({"name": "renamed", "is_default": True})
        self.assertEqual(ir_filter.name, "renamed")

    def test_rejects_truncated_domain(self):
        with self.assertRaises(ValidationError):
            self.env["ir.filters"].create_filter(
                {"name": "truncated", "model_id": "res.partner", "domain": "[("}
            )

    def test_rejects_top_level_non_list(self):
        with self.assertRaises(ValidationError):
            self.env["ir.filters"].create_filter(
                {"name": "dict", "model_id": "res.partner", "domain": "{'a': 1}"}
            )

    def test_rejects_non_whitelisted_name(self):
        hostile = "[('a','=',__import__('os').system('x'))]"
        with self.assertRaises(ValidationError):
            self.env["ir.filters"].create_filter(
                {"name": "hostile", "model_id": "res.partner", "domain": hostile}
            )
        with self.assertRaises(ValidationError):
            self._create_dynamic(hostile)

    def test_static_domain_still_accepted(self):
        ir_filter = self._create_dynamic("[('is_company', '=', True)]")
        self.assertEqual(ir_filter._get_eval_domain(), [("is_company", "=", True)])


@tagged("post_install", "-at_install")
class TestCrossUserWrite(FiltersCase):
    def test_internal_user_can_write_global_filter(self):
        global_filter = self.env["ir.filters"].create(
            {"name": "global", "model_id": "ir.filters", "user_ids": []}
        )
        global_filter.with_user(self.USER_ID).write({"name": "edited by demo"})
        self.assertEqual(global_filter.name, "edited by demo")


class TestSortColumnCheck(TransactionCase):
    def _create(self, sort):
        return self.env["ir.filters"].create(
            {
                "name": "sort check",
                "model_id": "res.partner",
                "domain": "[]",
                "context": "{}",
                "sort": sort,
            }
        )

    def _assert_rejected(self, sort):
        exc = None
        with mute_logger("odoo.db"):
            try:
                with self.env.cr.savepoint():
                    self._create(sort)
                    self.env.flush_all()
            except psycopg.errors.IntegrityError as error:
                exc = error
        self.assertIsNotNone(exc, f"sort={sort!r} was accepted")
        self.assertEqual(
            self.env["ir.filters"]._sql_error_to_message(exc),
            "Invalid sort definition",
        )

    def test_non_json_text_is_rejected_with_a_message(self):
        self._assert_rejected("not json")

    def test_empty_string_is_rejected_with_a_message(self):
        self._assert_rejected("")

    def test_json_object_is_rejected_with_a_message(self):
        self._assert_rejected('{"a": 1}')

    def test_json_array_is_accepted(self):
        self.assertEqual(self._create('["name asc"]').sort, '["name asc"]')
