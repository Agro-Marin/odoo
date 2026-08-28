import annotationlib
import inspect

from odoo.exceptions import UserError
from odoo.service.model import get_public_method
from odoo.tests import TransactionCase, tagged

from odoo.addons.rpc.tools.preflight import (
    CALL_SHAPES,
    DOMAIN,
    FIELD,
    FIELDS,
    GROUP,
    HAVING,
    ORDER,
    PATHS,
    SPEC,
    VALS,
    _close_field_names,
    _iter_grouping_specs,
    _iter_vals_dicts,
    _requested_fields,
    call_args,
    check_call,
    check_domain,
    check_grouping,
    check_order,
    check_requested_fields,
    check_write_values,
    mentioned_field_names,
)


@tagged("post_install", "-at_install")
class TestFieldPreflight(TransactionCase):
    def _params(self, method, args, kwargs=None):
        params = ["db", 1, "pw", "res.partner", method, args]
        if kwargs is not None:
            params.append(kwargs)
        return params

    def _fields_of(self, method, args, kwargs=None):
        positional, call_kwargs = call_args(self._params(method, args, kwargs))
        return _requested_fields(method, positional, call_kwargs)

    def _check_fields(self, model, method, args, kwargs=None):
        positional, call_kwargs = call_args(self._params(method, args, kwargs))
        check_requested_fields(self.env, model, method, positional, call_kwargs)

    def _check_dom(self, model, method, args, kwargs=None):
        positional, call_kwargs = call_args(self._params(method, args, kwargs))
        check_domain(self.env, model, method, positional, call_kwargs)

    def test_requested_fields_positional_and_kwargs(self):
        self.assertEqual(self._fields_of("read", [[1], ["name"]]), ["name"])
        self.assertEqual(
            self._fields_of("search_read", [[]], {"fields": ["name"]}), ["name"]
        )

    def test_requested_fields_returns_none_when_not_applicable(self):
        cases = {
            "other method": ("write", [[1], {"name": "x"}]),
            "omitted": ("read", [[1]]),
            "empty list": ("read", [[1], []]),
            "not a list": ("read", [[1], "name"]),
            "no args": ("read", []),
        }
        for label, (method, args) in cases.items():
            with self.subTest(case=label):
                self.assertIsNone(self._fields_of(method, args))

    def test_check_requested_fields_accepts_valid(self):
        self._check_fields("res.partner", "read", [[1], ["name", "email"]])

    def test_check_requested_fields_rejects_unknown(self):
        with self.assertRaises(UserError) as caught:
            self._check_fields(
                "res.partner", "read", [[1], ["name", "zzz_bogus_field_xyz"]]
            )
        message = str(caught.exception)
        self.assertIn("zzz_bogus_field_xyz", message)
        self.assertIn("res.partner", message)
        self.assertNotIn("'name'", message, "valid fields must not be reported")

    def test_check_requested_fields_suggests_close_match(self):
        partner_fields = self.env["res.partner"]._fields
        self.assertIn("commercial_partner_id", partner_fields)
        with self.assertRaises(UserError) as caught:
            self._check_fields("res.partner", "read", [[1], ["comercial_partner_id"]])
        self.assertIn("commercial_partner_id", str(caught.exception))

    def test_close_field_names_prefers_reordered_tokens(self):
        known = sorted(
            [
                "qty_available",
                "qty_available_virtual",
                "qty_free",
                "qty_incoming",
                "qty_outgoing",
                "reordering_qty_min",
                "suggested_qty",
                "name",
            ]
        )
        self.assertEqual(_close_field_names("free_qty", known), ["qty_free"])
        self.assertEqual(_close_field_names("incoming_qty", known), ["qty_incoming"])

    def test_close_field_names_falls_back_to_fuzzy(self):
        known = sorted(self.env["res.partner"]._fields)
        self.assertIn(
            "commercial_partner_id",
            _close_field_names("comercial_partner_id", known),
        )

    def test_close_field_names_stays_quiet_on_gibberish(self):
        known = sorted(self.env["res.partner"]._fields)
        self.assertEqual(_close_field_names("zzz_bogus_field_xyz", known), [])

    def test_check_requested_fields_ignores_unchecked_methods(self):
        self._check_fields("res.partner", "search", [[("name", "=", "x")]])
        self._check_fields("res.partner", "write", [[1], {"name": "x"}])

    def test_web_read_spec_top_level_keys_are_checked(self):
        self.assertEqual(
            self._fields_of("web_read", [[1], {"name": {}, "email": {}}]),
            ["name", "email"],
        )
        self.assertEqual(
            self._fields_of("web_read", [[1]], {"specification": {"name": {}}}),
            ["name"],
        )

    def test_web_name_search_spec_top_level_keys_are_checked(self):
        self.assertEqual(
            self._fields_of("web_name_search", ["", {"name": {}, "email": {}}]),
            ["name", "email"],
        )
        with self.assertRaises(UserError) as caught:
            self._check_fields(
                "res.partner", "web_name_search", ["", {"zzz_bogus": {}}]
            )
        self.assertIn("zzz_bogus", str(caught.exception))

    def test_web_search_read_spec_top_level_keys_are_checked(self):
        self.assertEqual(
            self._fields_of("web_search_read", [[], {"name": {}}]), ["name"]
        )
        self.assertEqual(
            self._fields_of("web_search_read", [[]], {"specification": {"email": {}}}),
            ["email"],
        )

    def test_web_read_unknown_top_level_field_is_a_caller_error(self):
        cases = {
            "web_read positional": ("web_read", [[1], {"zzz_bogus": {}}]),
            "web_search_read positional": ("web_search_read", [[], {"zzz_bogus": {}}]),
            "web_read kwarg": ("web_read", [[1]]),
        }
        kwargs_by_case = {"web_read kwarg": {"specification": {"zzz_bogus": {}}}}
        for label, (method, args) in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(UserError) as caught:
                    self._check_fields(
                        "res.partner", method, args, kwargs_by_case.get(label)
                    )
                self.assertIn("zzz_bogus", str(caught.exception))

    def test_web_read_nested_spec_is_left_to_core(self):
        self._check_fields(
            "res.partner",
            "web_read",
            [[1], {"country_id": {"fields": {"zzz_bogus": {}}}}],
        )

    def test_web_read_omitted_or_empty_spec_is_fine(self):
        self.assertIsNone(self._fields_of("web_read", [[1]]))
        self.assertIsNone(self._fields_of("web_read", [[1], {}]))


@tagged("post_install", "-at_install")
class TestDomainPreflight(TransactionCase):
    def _check(self, method, args, kwargs=None):
        check_domain(self.env, "res.partner", method, args, kwargs or {})

    def test_valid_domain_passes(self):
        self._check("search", [[("name", "=", "x")]])
        self._check("search_count", [["|", ("name", "=", "x"), ("id", ">", 1)]])

    def test_dotted_path_is_allowed(self):
        self._check("search", [[("country_id.code", "=", "MX")]])

    def test_unknown_field_is_a_caller_error(self):
        with self.assertRaises(UserError) as caught:
            self._check("search", [[("zzz_bogus_field_xyz", "=", 1)]])
        message = str(caught.exception)
        self.assertIn("zzz_bogus_field_xyz", message)
        self.assertIn("fields_get", message)

    def test_unknown_field_suggests_a_close_match(self):
        with self.assertRaises(UserError) as caught:
            self._check("search", [[("comercial_partner_id", "=", 1)]])
        self.assertIn("commercial_partner_id", str(caught.exception))

    def test_malformed_domain_is_a_caller_error(self):
        with self.assertRaises(UserError):
            self._check("search", [[1146, 2692, 2724]])

    def test_invalid_operator_is_a_caller_error(self):
        with self.assertRaises(UserError):
            self._check("search", [[("name", "notanoperator", "x")]])

    def test_domain_in_kwargs(self):
        with self.assertRaises(UserError):
            self._check(
                "search_read", [], {"domain": [("zzz_bogus_field_xyz", "=", 1)]}
            )

    def test_name_search_positional_domain_is_checked(self):
        with self.assertRaises(UserError) as caught:
            self._check("name_search", ["", [("zzz_bogus_field_xyz", "=", 1)]])
        self.assertIn("zzz_bogus_field_xyz", str(caught.exception))

    def test_web_name_search_positional_domain_is_checked(self):
        with self.assertRaises(UserError) as caught:
            self._check(
                "web_name_search",
                ["", {"display_name": {}}, [("zzz_bogus_field_xyz", "=", 1)]],
            )
        self.assertIn("zzz_bogus_field_xyz", str(caught.exception))

    def test_name_search_valid_domain_passes(self):
        self._check("name_search", ["ab", [("is_company", "=", True)]])
        self._check("web_name_search", ["ab", {"display_name": {}}, [("id", ">", 0)]])

    def test_methods_without_a_domain_are_untouched(self):
        self._check("write", [[1], {"name": "x"}])
        self._check("read", [[1], ["name"]])


@tagged("post_install", "-at_install")
class TestOrderPreflight(TransactionCase):
    def _check(self, method="search_read", args=(), **kwargs):
        check_order(self.env, "res.partner", method, list(args), kwargs)

    def test_valid_order_passes(self):
        self._check(order="name desc")
        self._check(order="name asc, id desc")

    def test_no_order_is_fine(self):
        self._check()
        self._check(order=None)
        self._check(order="")

    def test_unknown_order_field_is_a_caller_error(self):
        with self.assertRaises(UserError) as caught:
            self._check(order="zzz_bogus desc")
        self.assertIn("zzz_bogus", str(caught.exception))

    def test_unknown_order_field_suggests_a_close_match(self):
        with self.assertRaises(UserError) as caught:
            self._check(order="comercial_partner_id asc")
        self.assertIn("commercial_partner_id", str(caught.exception))

    def test_sorting_across_a_relation_is_a_caller_error(self):
        with self.assertRaises(UserError) as caught:
            self._check(order="parent_id.name")
        self.assertIn("relation", str(caught.exception))

    def test_the_orm_really_does_reject_it(self):
        with self.assertRaises(ValueError):
            self.env["res.partner"].sudo().search([], order="parent_id.name", limit=1)


@tagged("post_install", "-at_install")
class TestGroupingPreflight(TransactionCase):
    def _check(self, method, args, kwargs=None):
        check_grouping(self.env, "res.partner", method, args, kwargs or {})

    def test_iter_grouping_specs_flattens_grouping_sets(self):
        self.assertEqual(
            list(_iter_grouping_specs([["a", "b"], ["c"]])), ["a", "b", "c"]
        )
        self.assertEqual(list(_iter_grouping_specs("x")), ["x"])
        self.assertEqual(list(_iter_grouping_specs([1, None, "y"])), ["y"])

    def test_valid_grouping_passes(self):
        self._check("read_group", [[], ["__count"], ["country_id"]])
        self._check("read_group", [[], ["__count"], ["create_date:month"]])
        self._check("formatted_read_group", [[], ["country_id"], ["__count"]])
        self._check("formatted_read_group", [[], [], []], {})

    def test_unknown_groupby_field_is_a_caller_error(self):
        with self.assertRaises(UserError) as caught:
            self._check("read_group", [[], ["__count"], ["zzz_bogus"]])
        self.assertIn("zzz_bogus", str(caught.exception))

    def test_unknown_aggregate_field_is_a_caller_error(self):
        with self.assertRaises(UserError) as caught:
            self._check("formatted_read_group", [[], ["country_id"], ["zzz_bogus:sum"]])
        self.assertIn("zzz_bogus", str(caught.exception))

    def test_grouping_sets_unknown_field_is_a_caller_error(self):
        with self.assertRaises(UserError) as caught:
            self._check(
                "formatted_read_grouping_sets",
                [[], [["country_id"], ["zzz_bogus"]], ["__count"]],
            )
        self.assertIn("zzz_bogus", str(caught.exception))

    def test_kwargs_form_is_checked(self):
        with self.assertRaises(UserError):
            self._check("formatted_read_group", [[]], {"groupby": ["zzz_bogus"]})

    def test_close_match_is_suggested(self):
        with self.assertRaises(UserError) as caught:
            self._check("read_group", [[], ["__count"], ["country_idd"]])
        self.assertIn("country_id", str(caught.exception))

    def test_non_grouping_method_is_untouched(self):
        self._check("search", [[["zzz_bogus", "=", 1]]])


@tagged("post_install", "-at_install")
class TestWriteValuesPreflight(TransactionCase):
    def _check(self, method, args, kwargs=None):
        check_write_values(self.env, "res.partner", method, args, kwargs or {})

    def test_iter_vals_dicts_positions(self):
        self.assertEqual(list(_iter_vals_dicts("create", [{"a": 1}], {})), [{"a": 1}])
        self.assertEqual(
            list(_iter_vals_dicts("create", [[{"a": 1}, {"b": 2}]], {})),
            [{"a": 1}, {"b": 2}],
        )
        self.assertEqual(
            list(_iter_vals_dicts("write", [[1], {"a": 1}], {})), [{"a": 1}]
        )
        self.assertEqual(
            list(_iter_vals_dicts("write", [[1]], {"vals": {"a": 1}})), [{"a": 1}]
        )
        self.assertEqual(list(_iter_vals_dicts("copy", [[1]], {})), [])

    def test_valid_write_and_create_pass(self):
        self._check("write", [[1], {"name": "x", "comment": "y"}])
        self._check("create", [{"name": "x", "email": "e@e.com"}])
        self._check("create", [[{"name": "a"}, {"name": "b"}]])

    def test_command_tuple_values_are_not_read_as_fields(self):
        self._check("write", [[1], {"category_id": [(6, 0, [])]}])
        self._check("write", [[1], {"child_ids": [(0, 0, {"name": "kid"})]}])

    def test_unknown_field_in_each_write_method_is_400(self):
        cases = {
            "write positional": ("write", [[1], {"zzz_bogus": "x"}], None),
            "write kwarg": ("write", [[1]], {"vals": {"zzz_bogus": "x"}}),
            "create single": ("create", [{"name": "x", "zzz_bogus": 1}], None),
            "create multi": ("create", [[{"name": "a"}, {"zzz_bogus": 1}]], None),
            "copy default": ("copy", [[1], {"zzz_bogus": 1}], None),
        }
        for label, (method, args, kwargs) in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(UserError) as caught:
                    self._check(method, args, kwargs)
                self.assertIn("zzz_bogus", str(caught.exception))

    def test_nested_relational_vals_are_left_to_core(self):
        self._check("write", [[1], {"child_ids": [(0, 0, {"zzz_bogus": "x"})]}])

    def test_close_match_is_suggested(self):
        with self.assertRaises(UserError) as caught:
            self._check("write", [[1], {"comercial_partner_id": 1}])
        self.assertIn("commercial_partner_id", str(caught.exception))

    def test_non_write_method_is_untouched(self):
        self._check("search", [[["zzz_bogus", "=", 1]]])


@tagged("post_install", "-at_install")
class TestOrderPositions(TransactionCase):
    def _check(self, method, args, kwargs=None):
        check_order(self.env, "res.partner", method, list(args), kwargs or {})

    def test_positional_order_is_checked_for_every_method_that_takes_one(self):
        cases = {
            "search args[3]": ("search", [[], 0, None, "zzz_bogus desc"]),
            "search_read args[4]": (
                "search_read",
                [[], ["name"], 0, None, "zzz_bogus desc"],
            ),
            "web_search_read args[4]": (
                "web_search_read",
                [[], {"name": {}}, 0, None, "zzz_bogus desc"],
            ),
            "web_read_group args[5]": (
                "web_read_group",
                [[], ["country_id"], ["__count"], None, 0, "zzz_bogus desc"],
            ),
            "formatted_read_group args[6]": (
                "formatted_read_group",
                [[], ["country_id"], ["__count"], [], 0, None, "zzz_bogus desc"],
            ),
            "read_group args[5] (orderby)": (
                "read_group",
                [[], ["__count"], ["country_id"], 0, None, "zzz_bogus desc"],
            ),
        }
        for label, (method, args) in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(UserError) as caught:
                    self._check(method, args)
                self.assertIn("zzz_bogus", str(caught.exception))

    def test_read_group_names_its_sort_orderby_not_order(self):
        with self.assertRaises(UserError):
            self._check("read_group", [[]], {"orderby": "zzz_bogus desc"})

    def test_a_valid_positional_order_still_passes(self):
        self._check("search", [[], 0, None, "email desc"])
        self._check("read_group", [[], ["__count"], ["country_id"], 0, None, "id"])

    def test_an_order_on_a_method_that_takes_none_is_not_invented(self):
        self._check("write", [[1], {"name": "x"}], {"order": "zzz_bogus"})


@tagged("post_install", "-at_install")
class TestHavingPreflight(TransactionCase):
    def _check(self, args, kwargs=None):
        check_grouping(
            self.env, "res.partner", "formatted_read_group", list(args), kwargs or {}
        )

    def test_unknown_field_in_having_is_a_caller_error(self):
        for label, (args, kwargs) in {
            "positional args[3]": (
                [[], ["country_id"], ["__count"], [("zzz_bogus:max", ">", 0)]],
                None,
            ),
            "kwarg": ([[]], {"having": [("zzz_bogus:max", ">", 0)]}),
        }.items():
            with self.subTest(case=label):
                with self.assertRaises(UserError) as caught:
                    self._check(args, kwargs)
                self.assertIn("zzz_bogus", str(caught.exception))

    def test_a_valid_having_passes(self):
        self._check([[], ["country_id"], ["__count"], [("__count", ">", 1)]])
        self._check([[], ["country_id"], ["id:max"], [("id:max", ">", 1)]])


@tagged("post_install", "-at_install")
class TestNewlyCoveredMethods(TransactionCase):
    def _check(self, method, args, kwargs=None):
        check_call(self.env, "res.partner", method, list(args), kwargs or {})

    def test_each_newly_covered_method_rejects_a_stale_field(self):
        cases = {
            "web_save vals": ("web_save", [[1], {"zzz_bogus": "x"}, {"name": {}}]),
            "web_save specification": (
                "web_save",
                [[1], {"name": "x"}, {"zzz_bogus": {}}],
            ),
            "web_save_multi vals_list": (
                "web_save_multi",
                [[1], [{"zzz_bogus": "x"}], {"name": {}}],
            ),
            "onchange values": ("onchange", [[1], {"zzz_bogus": 1}, [], {}]),
            "onchange field_names": ("onchange", [[1], {}, ["zzz_bogus"], {}]),
            "onchange fields_spec": ("onchange", [[1], {}, [], {"zzz_bogus": {}}]),
            "default_get fields": ("default_get", [["zzz_bogus"]]),
            "load fields": ("load", [["zzz_bogus"], []]),
            "copy_data default": ("copy_data", [[1], {"zzz_bogus": 1}]),
            "read_progress_bar domain": (
                "read_progress_bar",
                [[("zzz_bogus", "=", 1)], "id", {}],
            ),
            "read_progress_bar group_by": (
                "read_progress_bar",
                [[], "zzz_bogus", {}],
            ),
            "read_progress_bar progress_bar['field']": (
                "read_progress_bar",
                [[], "country_id", {"field": "zzz_bogus", "colors": {}}],
            ),
            "web_read_group groupby_read_specification": (
                "web_read_group",
                [[], ["country_id"], ["__count"]],
            ),
        }
        kwargs_by_case = {
            "web_read_group groupby_read_specification": {
                "groupby_read_specification": {"zzz_bogus": {}}
            }
        }
        for label, (method, args) in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(UserError) as caught:
                    self._check(method, args, kwargs_by_case.get(label))
                self.assertIn("zzz_bogus", str(caught.exception))

    def test_the_same_calls_pass_when_every_name_is_real(self):
        self._check("web_save", [[1], {"name": "x"}, {"name": {}}])
        self._check("web_save_multi", [[1], [{"name": "x"}], {"name": {}}])
        self._check("onchange", [[1], {"name": "x"}, ["name"], {"name": {}}])
        self._check("default_get", [["name", "email"]])
        self._check("load", [["id", "name"], [["1", "x"]]])
        self._check("read_progress_bar", [[], "country_id", {"field": "name"}])
        self._check("read_progress_bar", [[], "country_id", {}])
        self._check("read_progress_bar", [[], "country_id", "not a dict"])

    def test_export_data_is_checked(self):
        self._check("export_data", [[1], ["name", "parent_id/name", "id", ".id"]])
        self._check("load", [["id", ".id", "parent_id/.id"], []])
        for label, (args, kwargs) in {
            "positional args[1]": ([[1], ["zzz_bogus"]], None),
            "kwarg": ([[1]], {"fields_to_export": ["zzz_bogus"]}),
            "export path": ([[1], ["zzz_bogus/name"]], None),
        }.items():
            with self.subTest(case=label):
                with self.assertRaises(UserError) as caught:
                    self._check("export_data", args, kwargs)
                self.assertIn("zzz_bogus", str(caught.exception))

    def test_load_reads_export_paths_by_their_leading_segment(self):
        self._check("load", [["id", "parent_id/name"], []])
        with self.assertRaises(UserError) as caught:
            self._check("load", [["zzz_bogus/name"], []])
        self.assertIn("zzz_bogus", str(caught.exception))


@tagged("post_install", "-at_install")
class TestMentionedFieldNames(TransactionCase):
    def _names(self, method, args, kwargs=None):
        return sorted(set(mentioned_field_names(method, list(args), kwargs or {})))

    def test_a_positional_sort_is_named(self):
        self.assertEqual(
            self._names("search_read", [[], ["id"], 0, 1, "email desc"]),
            ["email", "id"],
        )
        self.assertEqual(self._names("search", [[], 0, 1, "email desc"]), ["email"])
        self.assertEqual(
            self._names("read_group", [[], ["__count"], ["id"], 0, None, "email"]),
            ["email", "id"],
        )

    def test_every_shape_of_mention_is_named(self):
        cases = {
            "field list": (("read", [[1], ["name", "email"]]), ["email", "name"]),
            "specification": (("web_read", [[1], {"name": {}}]), ["name"]),
            "domain": (("search", [[("email", "=", "x")]]), ["email"]),
            "domain behind a name": (
                ("name_search", ["ab", [("email", "=", "x")]]),
                ["email"],
            ),
            "groupby": (
                ("formatted_read_group", [[], ["country_id"], ["__count"]]),
                ["country_id"],
            ),
            "having": (
                (
                    "formatted_read_group",
                    [[], ["id"], ["__count"], [("email:max", ">", "a")]],
                ),
                ["email", "id"],
            ),
            "vals": (("write", [[1], {"email": "x"}]), ["email"]),
            "web_save both halves": (
                ("web_save", [[1], {"email": "x"}, {"phone": {}}]),
                ["email", "phone"],
            ),
        }
        for label, ((method, args), expected) in cases.items():
            with self.subTest(case=label):
                self.assertEqual(self._names(method, args), expected)

    def test_pseudo_fields_are_not_named(self):
        self.assertEqual(
            self._names("formatted_read_group", [[], ["id"], ["__count"]]), ["id"]
        )

    def test_only_the_leading_segment_of_a_path_is_named(self):
        self.assertEqual(
            self._names("search", [[("parent_id.email", "=", "x")]]), ["parent_id"]
        )
        self.assertEqual(
            self._names("read_group", [[], ["__count"], ["create_date:month"]]),
            ["create_date"],
        )

    def test_a_malformed_call_names_nothing_rather_than_raising(self):
        self.assertEqual(self._names("search", [["not", "a", "domain"]]), [])
        self.assertEqual(self._names("read", [[1], "name"]), [])
        self.assertEqual(self._names("write", [[1], "not a dict"]), [])
        self.assertEqual(self._names("nonexistent_method", [[1], ["name"]]), [])


@tagged("post_install", "-at_install")
class TestCallShapesMatchTheOrm(TransactionCase):
    UNCOVERED = {
        "fields_get",
        "check_field_access_rights",
        "get_gantt_data",
        "get_cohort_data",
        "grid_unavailability",
        "grid_update_cell",
        "web_gantt_reschedule",
        "web_gantt_init_old_vals_per_pill_id",
        "ai_find_default_records",
        "web_override_translations",
    }

    def _universal_methods(self):
        names = None
        for model_name in self.env.registry.models:
            public = {n for n in dir(type(self.env[model_name])) if n[0] != "_"}
            names = public if names is None else names & public
        return names or set()

    def _public_methods(self, model):
        for name in dir(type(model)):
            if name.startswith("_"):
                continue
            try:
                func = get_public_method(model, name)
                signature = inspect.signature(
                    func, annotation_format=annotationlib.Format.FORWARDREF
                )
            except Exception:  # noqa: S112  not a public method, or unreadable
                continue
            yield name, func, signature

    def test_every_recorded_index_matches_the_live_signature(self):
        model = self.env["res.partner"]
        for name, func, signature in self._public_methods(model):
            shape = CALL_SHAPES.get(name)
            if not shape:
                continue
            positional = [
                p
                for p in signature.parameters.values()
                if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                and p.name != "self"
            ]
            offset = 0 if getattr(func, "_api_model", False) else 1
            expected = {p.name: i + offset for i, p in enumerate(positional)}
            for argument in shape:
                with self.subTest(method=name, argument=argument.name):
                    self.assertIn(
                        argument.name,
                        signature.parameters,
                        f"{name}() has no parameter {argument.name!r}",
                    )
                    self.assertEqual(
                        argument.index,
                        expected.get(argument.name),
                        f"{name}({argument.name}) is at "
                        f"{expected.get(argument.name)}, not {argument.index}",
                    )

    def test_no_universal_method_carries_an_undescribed_field_argument(self):
        described = {a.name for shape in CALL_SHAPES.values() for a in shape}
        described |= {"field_names", "allfields", "group_by"}
        universal = self._universal_methods()
        missing = {}
        for name, _func, signature in self._public_methods(self.env["res.partner"]):
            if name not in universal or name in CALL_SHAPES or name in self.UNCOVERED:
                continue
            if carried := described & set(signature.parameters):
                missing[name] = sorted(carried)
        self.assertEqual(
            missing,
            {},
            "method(s) on the universal model surface carry a field-name "
            "argument that CALL_SHAPES does not describe; add a row, or add "
            "the name to UNCOVERED with the reason it is not ours to check",
        )

    def test_the_uncovered_roster_does_not_overlap_the_table(self):
        self.assertEqual(sorted(self.UNCOVERED & set(CALL_SHAPES)), [])

    def test_a_field_list_that_can_be_omitted_means_every_field(self):
        model = self.env["res.partner"]
        signature = inspect.signature(
            get_public_method(model, "export_data"),
            annotation_format=annotationlib.Format.FORWARDREF,
        )
        parameter = signature.parameters["fields_to_export"]
        self.assertIs(parameter.default, inspect.Parameter.empty)

    def test_every_described_method_exists(self):
        model = self.env["res.partner"]
        absent = [name for name in CALL_SHAPES if not hasattr(model, name)]
        self.assertEqual(absent, [])


@tagged("post_install", "-at_install")
class TestCheckCall(TransactionCase):
    def test_check_call_runs_every_check(self):
        cases = {
            "field list": ("read", [[1], ["zzz_bogus"]]),
            "domain": ("search", [[("zzz_bogus", "=", 1)]]),
            "order": ("search", [[], 0, None, "zzz_bogus desc"]),
            "grouping": ("read_group", [[], ["__count"], ["zzz_bogus"]]),
            "values": ("write", [[1], {"zzz_bogus": 1}]),
        }
        for label, (method, args) in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(UserError) as caught:
                    check_call(self.env, "res.partner", method, args, {})
                self.assertIn("zzz_bogus", str(caught.exception))

    def test_a_wholly_valid_call_passes(self):
        check_call(
            self.env,
            "res.partner",
            "search_read",
            [[("name", "=", "x")], ["name"], 0, 10, "email desc"],
            {},
        )

    def test_the_check_order_is_the_one_the_call_sites_already_had(self):
        cases = {
            "field list beats domain": (
                ("search_read", [[("zzz_dom", "=", 1)], ["zzz_fld"]]),
                "zzz_fld",
            ),
            "domain beats order": (
                ("search_read", [[("zzz_dom", "=", 1)], ["name"], 0, 1, "zzz_ord"]),
                "zzz_dom",
            ),
            "domain beats grouping": (
                ("read_group", [[("zzz_dom", "=", 1)], ["__count"], ["zzz_grp"]]),
                "zzz_dom",
            ),
        }
        for label, ((method, args), expected) in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(UserError) as caught:
                    check_call(self.env, "res.partner", method, args, {})
                self.assertIn(expected, str(caught.exception))

    def test_the_kinds_are_the_ones_the_table_uses(self):
        used = {argument.kind for shape in CALL_SHAPES.values() for argument in shape}
        self.assertEqual(
            used, {FIELD, FIELDS, PATHS, SPEC, DOMAIN, ORDER, GROUP, HAVING, VALS}
        )
