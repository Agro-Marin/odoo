"""The argument pre-flights: a caller's mistake, reported as one.

Moved here with the code they cover (ADR-0023). They were written in
`agromarin/mcp_server`, where the fault they close was first measured, and the
functions now live in `rpc` because they are written against `call_kw` argument
positions rather than against anything one protocol owns.

`res.partner` is the model under test throughout: it is in `base`, so these run
without any addon this module does not already depend on.
"""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.rpc.tools.preflight import (
    _close_field_names,
    _iter_grouping_specs,
    _iter_vals_dicts,
    _requested_fields,
    call_args,
    check_domain,
    check_grouping,
    check_order,
    check_requested_fields,
    check_write_values,
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

    def _check(self, **kwargs):
        check_order(self.env, "res.partner", kwargs)

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
