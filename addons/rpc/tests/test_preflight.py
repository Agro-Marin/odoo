"""The argument pre-flights: a caller's mistake, reported as one.

Moved here with the code they cover (ADR-0023). They were written in
`agromarin/mcp_server`, where the fault they close was first measured, and the
functions now live in `rpc` because they are written against `call_kw` argument
positions rather than against anything one protocol owns.

`res.partner` is the model under test throughout: it is in `base`, so these run
without any addon this module does not already depend on.
"""

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
        """read/search_read carry the field list as args[1] or kwargs['fields']."""
        self.assertEqual(self._fields_of("read", [[1], ["name"]]), ["name"])
        self.assertEqual(
            self._fields_of("search_read", [[]], {"fields": ["name"]}), ["name"]
        )

    def test_requested_fields_returns_none_when_not_applicable(self):
        cases = {
            "other method": ("write", [[1], {"name": "x"}]),
            # An omitted or empty list means "every field"; validating it would
            # reject nothing but must not blow up either.
            "omitted": ("read", [[1]]),
            "empty list": ("read", [[1], []]),
            "not a list": ("read", [[1], "name"]),
            "no args": ("read", []),
        }
        for label, (method, args) in cases.items():
            with self.subTest(case=label):
                self.assertIsNone(self._fields_of(method, args))

    def test_check_requested_fields_accepts_valid(self):
        """A call naming only real fields passes through untouched."""
        self._check_fields("res.partner", "read", [[1], ["name", "email"]])

    def test_check_requested_fields_rejects_unknown(self):
        """An unknown field is a caller error, not silently dropped."""
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
        """search/write/etc. dispatch unexamined by the field check."""
        self._check_fields("res.partner", "search", [[("name", "=", "x")]])
        self._check_fields("res.partner", "write", [[1], {"name": "x"}])

    def test_web_read_spec_top_level_keys_are_checked(self):
        """web_read's spec sits at args[1] (record method: args[0] is the ids),
        and as the `specification` kwarg. Both forms are validated."""
        # positional -- args[0] is the ids, args[1] the specification
        self.assertEqual(
            self._fields_of("web_read", [[1], {"name": {}, "email": {}}]),
            ["name", "email"],
        )
        # kwarg
        self.assertEqual(
            self._fields_of("web_read", [[1]], {"specification": {"name": {}}}),
            ["name"],
        )

    def test_web_name_search_spec_top_level_keys_are_checked(self):
        """web_name_search runs web_read(spec) on its hits; spec is args[1]
        (name, specification, domain), so its keys are field-checked too."""
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
        """web_search_read is @api.model: args[0] is the domain, args[1] the spec."""
        self.assertEqual(
            self._fields_of("web_search_read", [[], {"name": {}}]), ["name"]
        )
        self.assertEqual(
            self._fields_of("web_search_read", [[]], {"specification": {"email": {}}}),
            ["email"],
        )

    def test_web_read_unknown_top_level_field_is_a_caller_error(self):
        # (method, args) -- args[0] is ids (web_read) or domain (web_search_read),
        # args[1] the specification in both.
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
        """Only the top-level keys are field names; a stale field inside a
        relation's sub-specification must NOT be rejected here."""
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
    """A stale field in a *domain* used to come back as fault 500.

    Same class of caller mistake as an unknown field in a read's field list,
    which was already handled -- but domains raise a bare ValueError out of the
    ORM, so they fell through to "Internal Server Error" plus an ERROR with a
    traceback that the log-viewer alerts on.
    """

    def _check(self, method, args, kwargs=None):
        check_domain(self.env, "res.partner", method, args, kwargs or {})

    def test_valid_domain_passes(self):
        self._check("search", [[("name", "=", "x")]])
        self._check("search_count", [["|", ("name", "=", "x"), ("id", ">", 1)]])

    def test_dotted_path_is_allowed(self):
        """Only the leading segment is ours to check; validate() walks the rest."""
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
        """A raw list of ids where a domain belongs -- seen in production."""
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
        """name_search's domain is args[1] (name is args[0]); the kwarg form was
        already caught, the positional form fell through to 500."""
        with self.assertRaises(UserError) as caught:
            self._check("name_search", ["", [("zzz_bogus_field_xyz", "=", 1)]])
        self.assertIn("zzz_bogus_field_xyz", str(caught.exception))

    def test_web_name_search_positional_domain_is_checked(self):
        """web_name_search's domain is args[2] (name, specification, domain)."""
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
    """A stale field in `order` was the third shape of the same 500."""

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
        """The ORM cannot sort across a relation; it answered 500 for 17 rows."""
        with self.assertRaises(UserError) as caught:
            self._check(order="parent_id.name")
        self.assertIn("relation", str(caught.exception))

    def test_the_orm_really_does_reject_it(self):
        """Pin the premise, so this stops rejecting if the ORM ever allows it."""
        with self.assertRaises(ValueError):
            self.env["res.partner"].sudo().search([], order="parent_id.name", limit=1)


@tagged("post_install", "-at_install")
class TestGroupingPreflight(TransactionCase):
    """A stale field in a read_group groupby/aggregate was the fourth 500.

    The domain on the same call was already pre-flighted; the groupby and the
    aggregate list were not, so `read_group([], ['__count'], ['stale_field'])`
    fell through to fault 500.
    """

    def _check(self, method, args, kwargs=None):
        check_grouping(self.env, "res.partner", method, args, kwargs or {})

    def test_iter_grouping_specs_flattens_grouping_sets(self):
        """grouping_sets nests one level; a non-spec element yields nothing."""
        self.assertEqual(
            list(_iter_grouping_specs([["a", "b"], ["c"]])), ["a", "b", "c"]
        )
        self.assertEqual(list(_iter_grouping_specs("x")), ["x"])
        self.assertEqual(list(_iter_grouping_specs([1, None, "y"])), ["y"])

    def test_valid_grouping_passes(self):
        # read_group(domain, fields, groupby); granularity and __count are fine.
        self._check("read_group", [[], ["__count"], ["country_id"]])
        self._check("read_group", [[], ["__count"], ["create_date:month"]])
        # formatted_read_group(domain, groupby, aggregates)
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
        # search carries a domain, not a groupby; this validator must ignore it.
        self._check("search", [[["zzz_bogus", "=", 1]]])


@tagged("post_install", "-at_install")
class TestWriteValuesPreflight(TransactionCase):
    """A stale field in a create/write/copy vals dict was a fault 500.

    write raised a bare `KeyError: 'field'`, create/copy an `Invalid field`
    ValueError -- the write-side twin of the read-list pre-flight.
    """

    def _check(self, method, args, kwargs=None):
        check_write_values(self.env, "res.partner", method, args, kwargs or {})

    def test_iter_vals_dicts_positions(self):
        # create: vals at args[0], single dict or list of dicts
        self.assertEqual(list(_iter_vals_dicts("create", [{"a": 1}], {})), [{"a": 1}])
        self.assertEqual(
            list(_iter_vals_dicts("create", [[{"a": 1}, {"b": 2}]], {})),
            [{"a": 1}, {"b": 2}],
        )
        # write/copy: record methods, args[0] is ids, vals at args[1]
        self.assertEqual(
            list(_iter_vals_dicts("write", [[1], {"a": 1}], {})), [{"a": 1}]
        )
        self.assertEqual(
            list(_iter_vals_dicts("write", [[1]], {"vals": {"a": 1}})), [{"a": 1}]
        )
        # copy with no default yields nothing
        self.assertEqual(list(_iter_vals_dicts("copy", [[1]], {})), [])

    def test_valid_write_and_create_pass(self):
        self._check("write", [[1], {"name": "x", "comment": "y"}])
        self._check("create", [{"name": "x", "email": "e@e.com"}])
        self._check("create", [[{"name": "a"}, {"name": "b"}]])

    def test_command_tuple_values_are_not_read_as_fields(self):
        """The keys are field names; a Command tuple sits in the value."""
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
        """Only top-level keys are checked; a stale field inside a Command
        tuple's nested vals is core's to reject, not this pre-flight's."""
        self._check("write", [[1], {"child_ids": [(0, 0, {"zzz_bogus": "x"})]}])

    def test_close_match_is_suggested(self):
        with self.assertRaises(UserError) as caught:
            self._check("write", [[1], {"comercial_partner_id": 1}])
        self.assertIn("commercial_partner_id", str(caught.exception))

    def test_non_write_method_is_untouched(self):
        self._check("search", [[["zzz_bogus", "=", 1]]])


@tagged("post_install", "-at_install")
class TestOrderPositions(TransactionCase):
    """`order` is not uniformly a keyword called `order`, and was read as if it were.

    `search` puts it at args[3], `search_read` and `web_search_read` at args[4],
    `web_read_group` at args[5], `formatted_read_group` at args[6], and
    `read_group` names it `orderby`. Reading only ``kwargs["order"]`` let every
    positional sort through unchecked and `read_group`'s through in both forms,
    while the keyword form of the very same call was refused -- so the check
    was one a caller stepped around by moving an argument.
    """

    def _check(self, method, args, kwargs=None):
        check_order(self.env, "res.partner", method, list(args), kwargs or {})

    def test_positional_order_is_checked_for_every_method_that_takes_one(self):
        cases = {
            # (method, args) -- the stale order sits at the recorded index
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
        """The one method whose keyword differs; keyed on the name alone it was
        missed in both forms."""
        with self.assertRaises(UserError):
            self._check("read_group", [[]], {"orderby": "zzz_bogus desc"})

    def test_a_valid_positional_order_still_passes(self):
        self._check("search", [[], 0, None, "email desc"])
        self._check("read_group", [[], ["__count"], ["country_id"], 0, None, "id"])

    def test_an_order_on_a_method_that_takes_none_is_not_invented(self):
        """`write` has no sort argument; a stray `order` kwarg is not one."""
        self._check("write", [[1], {"name": "x"}], {"order": "zzz_bogus"})


@tagged("post_install", "-at_install")
class TestHavingPreflight(TransactionCase):
    """`formatted_read_group(having=...)` filters on aggregate specs.

    Its left-hand sides are `amount:sum`-shaped, so `Domain.validate` refuses
    them as field names and `check_domain` cannot own it; nothing else looked
    at it either, which left a whole filtering argument unchecked.
    """

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
    """Public, field-name-bearing methods the tables did not list at all.

    `web_save` is the sharpest: it is `write` and `web_read` fused, the method a
    modern client reaches for first, and it carries a vals dict AND a read
    specification. `write` and `read` were both pre-flighted; the call that does
    both at once was not.
    """

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
            # The one field name that sits inside a dict of options rather
            # than being an argument of its own.
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
        # A progress_bar that is not a dict, or names no field, is core's to
        # reject; it must not be read as an unknown field here.
        self._check("read_progress_bar", [[], "country_id", {}])
        self._check("read_progress_bar", [[], "country_id", "not a dict"])

    def test_export_data_is_checked(self):
        """`export_data` returns values under `{"datas": ...}`, so a policy
        filtering a result by its keys cannot reach them: the field list is the
        only place to refuse."""
        # `.id` and `id/.id` are ordinary export paths whose leading segment
        # is empty; rejecting them would refuse a perfectly normal export.
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
        """`load` names fields the export way -- `parent_id/name`, not a dot."""
        self._check("load", [["id", "parent_id/name"], []])
        with self.assertRaises(UserError) as caught:
            self._check("load", [["zzz_bogus/name"], []])
        self.assertIn("zzz_bogus", str(caught.exception))


@tagged("post_install", "-at_install")
class TestMentionedFieldNames(TransactionCase):
    """`mentioned_field_names` is the sole input to a *policy*, not a diagnostic.

    `agromarin/mcp_server/field_denial` asks it which fields a call names and
    refuses the call when one of them is hidden. A name it misses is a field
    the denial does not cover, so a gap here is a disclosure oracle rather than
    a worse error message -- and it had no test of its own at all.
    """

    def _names(self, method, args, kwargs=None):
        return sorted(set(mentioned_field_names(method, list(args), kwargs or {})))

    def test_a_positional_sort_is_named(self):
        """The bypass this class exists for: the keyword form was seen, the
        positional form was not, and the ORM honours both."""
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
        """`__count` is not a field and cannot be denied; reporting it as one
        made the answer disagree with what `check_grouping` skips."""
        self.assertEqual(
            self._names("formatted_read_group", [[], ["id"], ["__count"]]), ["id"]
        )

    def test_only_the_leading_segment_of_a_path_is_named(self):
        """A path's tail resolves against a comodel, which has its own policy."""
        self.assertEqual(
            self._names("search", [[("parent_id.email", "=", "x")]]), ["parent_id"]
        )
        self.assertEqual(
            self._names("read_group", [[], ["__count"], ["create_date:month"]]),
            ["create_date"],
        )

    def test_a_malformed_call_names_nothing_rather_than_raising(self):
        """Best-effort by construction: a call the ORM will refuse anyway is not
        this function's to report on."""
        self.assertEqual(self._names("search", [["not", "a", "domain"]]), [])
        self.assertEqual(self._names("read", [[1], "name"]), [])
        self.assertEqual(self._names("write", [[1], "not a dict"]), [])
        self.assertEqual(self._names("nonexistent_method", [[1], ["name"]]), [])


@tagged("post_install", "-at_install")
class TestCallShapesMatchTheOrm(TransactionCase):
    """The table is a claim about live ORM signatures; check it against them.

    Every index is what a caller puts on the wire, and getting one wrong is
    silent in both directions -- too low and a check reads the wrong argument,
    too high and it reads nothing. Re-derive them rather than trusting the
    table, and fail when a public method grows a field-name argument the table
    does not list, which is how `web_save` came to be checked by nothing.
    """

    #: Methods on the universal surface that carry a field name and that
    #: `CALL_SHAPES` deliberately does not describe. Each needs a reason, and
    #: the point of the roster is that a NEW name cannot join it by accident.
    #: Entries may name methods a given database does not have -- the
    #: enterprise ones below are absent from a community install -- so absence
    #: is normal and is not asserted against.
    UNCOVERED = {
        # Metadata, not values: names a field to describe it, not to read it.
        "fields_get",
        # Answers "may I read this", so refusing it would be the very oracle
        # it is asked to report on.
        "check_field_access_rights",
        # Enterprise view helpers. Each carries several field-name arguments at
        # once -- a read_specification, a measure, two date fields, sets of
        # unavailability and progress-bar fields -- and describing half of one
        # is worse than describing none, because a partial row reads as cover.
        "get_gantt_data",
        "get_cohort_data",
        "grid_unavailability",
        "grid_update_cell",
        "web_gantt_reschedule",
        "web_gantt_init_old_vals_per_pill_id",
        "ai_find_default_records",
        # Overrides a translation for the *UI*, keyed by source term rather
        # than by field.
        "web_override_translations",
    }

    def _universal_methods(self):
        """Public method names every model in the registry has.

        `CALL_SHAPES` describes the generic call surface -- what any model
        answers to over `call_kw` -- so that is the surface to hold it against.
        Scanning every method of every model instead makes the gate fire on
        `ir.cron.toggle(model, domain)`, whose domain is written against
        *another* model and would be wrong to check here, and drowns a real
        omission in a dozen such.
        """
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
            # call_kw prefixes a record method's args with the ids; an
            # @api.model method's args[0] is its own first parameter.
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
        """A new field-name argument fails here instead of joining the silent
        ones. `web_save` was silent for as long as it existed."""
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
        """A name in both is a method described AND excused, and a reader
        cannot tell which of the two was meant.

        Deliberately NOT "every roster name exists": most of them come from
        modules a given database need not have, so absence is the normal case
        and asserting against it fails at every install scope but the widest.
        Measured: base+web only, that assertion fails on all seven enterprise
        entries.
        """
        self.assertEqual(sorted(self.UNCOVERED & set(CALL_SHAPES)), [])

    def test_a_field_list_that_can_be_omitted_means_every_field(self):
        """Pin the premise the write-side of the denial rests on.

        A check that refuses *named* fields is routed around by naming none --
        which is why `read`'s optional field list is left alone and the result
        filtered instead. `export_data` is safe to refuse at the field list
        ONLY because it has no default: give it one upstream and omitting the
        argument becomes "export everything", past a check that sees nothing
        named. `export_data` also returns its values under a key of its own
        (`{"datas": ...}`), which a result filter cannot see into, so there is
        no second line of defence to fall back on.
        """
        model = self.env["res.partner"]
        signature = inspect.signature(
            get_public_method(model, "export_data"),
            annotation_format=annotationlib.Format.FORWARDREF,
        )
        parameter = signature.parameters["fields_to_export"]
        self.assertIs(parameter.default, inspect.Parameter.empty)

    def test_every_described_method_exists(self):
        """A table row for a method no model has is a check that never runs."""
        model = self.env["res.partner"]
        absent = [name for name in CALL_SHAPES if not hasattr(model, name)]
        self.assertEqual(absent, [])


@tagged("post_install", "-at_install")
class TestCheckCall(TransactionCase):
    """Both consumers ran the five checks in a block; that block is a function."""

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
        """A call wrong in two ways reports whichever check runs first, so the
        order is observable behaviour, not an implementation detail. Pin it:
        with the domain moved last, the second case below reports the order
        instead of the domain."""
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
        """A kind constant nothing lists is a check wired to nothing."""
        used = {argument.kind for shape in CALL_SHAPES.values() for argument in shape}
        self.assertEqual(
            used, {FIELD, FIELDS, PATHS, SPEC, DOMAIN, ORDER, GROUP, HAVING, VALS}
        )
