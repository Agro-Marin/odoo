import ast
import textwrap
from pathlib import Path

import pytest
from naming_vocabulary import (
    ABOLISHED,
    RESERVED,
    ROOT,
    SCAN_ROOTS,
    SQL_RESERVED,
    Violation,
    _python_files,
    classify,
    collection_head_order,
    governed_definitions,
    governs_module_helpers,
    is_model_class,
    measure,
    producer_without_product,
    reserved_misuse,
)


def _cls(src: str) -> ast.ClassDef:
    return next(
        n
        for n in ast.walk(ast.parse(textwrap.dedent(src)))
        if isinstance(n, ast.ClassDef)
    )


@pytest.mark.parametrize(
    ("name", "canonical"),
    [
        ("_validate_amount", "_check_"),
        ("_verify_signature", "_check_"),
        ("_ensure_partner", "_check_"),
        ("_fetch_lines", "_get_"),
        ("_retrieve_token", "_get_"),
        ("_assign_owner", "_update_"),
        ("_delete_old_orders", "_remove_"),
        ("_append_tax", "_add_"),
    ],
)
def test_abolished_verbs_are_flagged(name, canonical):
    assert classify(name) is not None
    assert classify(name)[1] == canonical


@pytest.mark.parametrize("verb", sorted(RESERVED))
def test_a_reserved_verb_is_not_an_abolished_one(verb):
    assert classify(f"_{verb}_table") is None
    assert verb not in ABOLISHED


def test_only_the_checkable_reservations_are_enforced():
    """The five whose reservation no AST can settle stay documentation."""
    assert set(SQL_RESERVED) < set(RESERVED)
    assert set(RESERVED) - set(SQL_RESERVED) == {
        "parse",
        "decode",
        "index",
        "push",
        "discard",
    }


def _fn(src: str) -> ast.FunctionDef:
    return next(
        n
        for n in ast.walk(ast.parse(textwrap.dedent(src)))
        if isinstance(n, ast.FunctionDef)
    )


@pytest.mark.parametrize(
    ("src", "canonical"),
    [
        (
            "def _insert_view_mode(self, xmlids, mode):\n    modes.insert(1, mode)",
            "_add_",
        ),
        ("def _drop_stale_rows(self, rows):\n    rows.unlink()", "_remove_"),
        ("def insert_tag(self, tag):\n    self.tags.append(tag)", "_add_"),
    ],
)
def test_a_reserved_verb_is_flagged_when_the_body_does_not_earn_it(src, canonical):
    assert reserved_misuse(_fn(src)) == canonical


@pytest.mark.parametrize(
    "src",
    [
        # runs the statement
        "def _insert_row(self, vals):\n    self.env.cr.execute('INSERT INTO t VALUES (1)')",
        "def _drop_table(self, name):\n    self.env.cr.execute(SQL('DROP TABLE %s', name))",
        # assembles a fragment of it for a caller that runs it
        "def _insert_extra_columns(self) -> dict[str, SQL]:\n    return {}",
        # the SQL is a bare literal handed on
        "def _drop_index(self, name):\n    return 'DROP INDEX %s'",
        # list.insert: the caller supplies the position
        "def insert_paths(self, paths, bundle, index):\n    self.list[index:index] = paths",
        "def insert_step(self, step, *, position):\n    self.steps.insert(position, step)",
        # no object -- the bare verb is out of this gate, as for ABOLISHED
        "def insert(self, row):\n    self.rows.append(row)",
        # a position parameter does not rescue `drop`, which has no list idiom
        "def _drop_at(self, index):\n    del self.rows[index]",
    ],
)
def test_a_reserved_verb_the_body_earns_is_quiet(src):
    node = _fn(src)
    assert (reserved_misuse(node) is None) is not node.name.startswith("_drop_at")


def test_delegating_to_a_sibling_of_the_same_verb_keeps_the_verb():
    node = _fn(
        "def _drop_indexes(self, names):\n"
        "    for name in names:\n"
        "        self._drop_index(name)"
    )
    assert reserved_misuse(node) is None


@pytest.mark.parametrize(
    "src",
    [
        # a DIFFERENT verb is not delegation -- this is the laundering case
        "def _drop_stale(self, rows):\n    self._remove_rows(rows)",
        # recursing on itself is not delegation either
        "def _drop_tree(self, node):\n    self._drop_tree(node.child)",
    ],
)
def test_delegation_does_not_launder_an_unearned_verb(src):
    assert reserved_misuse(_fn(src)) == "_remove_"


def test_the_reserved_rule_reaches_measure(tmp_path):
    (tmp_path / "__manifest__.py").write_text("{}")
    models = tmp_path / "models"
    models.mkdir()
    (models / "a.py").write_text(
        textwrap.dedent("""
            class Thing(models.Model):
                _name = "thing"

                def _insert_view_mode(self, mode):
                    self.modes.insert(1, mode)

                def _insert_row(self, vals):
                    self.env.cr.execute("INSERT INTO t VALUES (1)")
        """)
    )
    found = measure([tmp_path])
    assert [(v.name, v.verb, v.canonical) for v in found] == [
        ("_insert_view_mode", "insert", "_add_")
    ]


@pytest.mark.parametrize(
    "name",
    [
        "_prepare_invoice_vals",
        "_get_lines",
        "_check_date",
        "_compute_amount",
        "action_confirm",
        "create",
        "write",
        "__init__",
        "_validate",
    ],
)
def test_compliant_and_framework_names_are_quiet(name):
    assert classify(name) is None


def test_the_payload_suffix_chooses_an_assemble_verbs_canonical_not_its_reach():
    assert classify("_build_invoice_vals") == ("build", "_prepare_")
    assert classify("_make_line_values") == ("make", "_prepare_")
    assert classify("_build_url") == ("build", "_get_")
    assert classify("_compose_email") == ("compose", "_get_")
    assert classify("_assemble_registry") == ("assemble", "_get_")
    assert classify("_craft_line_vals") == ("craft", "_prepare_")


def test_synchronize_lands_on_the_reservation_or_the_payload_row():
    # §2.4.3 reserves `_sync_` for convergence on a source of truth elsewhere,
    # and three of the workspace's eight `_synchronize_*` RETURN a values dict
    # and write nothing -- the Payload row, which the suffix is what says.
    assert classify("_synchronize_crons") == ("synchronize", "_sync_")
    assert classify("_synchronise_state_and_active") == ("synchronise", "_sync_")
    assert classify("_synchronize_partner_values") == ("synchronize", "_prepare_")


@pytest.mark.parametrize(
    ("name", "canonical"),
    [
        ("_populate_lines", "_update_"),
        ("_tweak_recipients", "_update_"),
        ("_prune_versions", "_remove_"),
        ("_sweep_stale_rows", "_remove_"),
        ("_seed_catalog_weights", "_create_"),
        ("_scan_network", "_read_"),
        ("_detect_is_bounce", "_is_"),
        ("_determine_next_page", "_get_"),
        ("_calculate_distance", "_get_"),
    ],
)
def test_the_synonyms_of_a_row_are_flagged_with_the_rows_canonical(name, canonical):
    # §2.4.20: the table is families, not a word list. These were core-only
    # readings until the addon floors were read against them.
    assert classify(name) == (name.lstrip("_").partition("_")[0], canonical)


@pytest.mark.parametrize(
    "name",
    [
        "_refresh_google_token",
        "_find_available_name",
        "_filter_overdue_amls",
        "_collect_qty_changes",
        "_complete_quest",
        "emit",
        "locate_node",
    ],
)
def test_the_words_the_table_declines_stay_out(name):
    # Argued in the ABOLISHED comment: two reserved senses of `refresh` in
    # addons/, and five words whose row only the body can pick.
    assert classify(name) is None


def test_an_infix_synonym_is_a_candidate_like_an_infix_abolished_verb():
    from naming_vocabulary import infix_abolished_verb

    assert infix_abolished_verb("_action_populate_lines") == "populate"
    assert infix_abolished_verb("_cron_synchronize_partners") == "synchronize"
    # The assemble verbs keep §2.4.4's narrower reading behind a noun.
    assert infix_abolished_verb("_report_build_lines") is None
    assert infix_abolished_verb("_report_build_vals") == "build"
    # §2.4.20: a predicate prefix suspends the infix rule.
    assert infix_abolished_verb("can_scan_identity") is None
    assert infix_abolished_verb("is_refresh_due") is None


def test_a_bare_assemble_verb_stays_out_of_this_gate():
    assert classify("_build") is None
    assert classify("make") is None


@pytest.mark.parametrize(
    "src",
    [
        "class SaleOrder(models.Model):\n    _name = 'sale.order'",
        "class Wiz(models.TransientModel):\n    _name = 'w'",
        "class Mixin(models.AbstractModel):\n    _name = 'm'",
        "class Extend(SomethingElse):\n    _inherit = 'sale.order'",
    ],
)
def test_model_classes_are_in_scope(src):
    assert is_model_class(_cls(src))


@pytest.mark.parametrize(
    "src",
    [
        "class Cursor:\n    def _drop_table(self): pass",
        "class Session(dict):\n    def remove_old_sessions(self): pass",
        "class Registry(Mapping):\n    def discard_field(self): pass",
    ],
)
def test_framework_classes_are_out_of_scope(src):
    assert not is_model_class(_cls(src))


def test_measure_refuses_an_empty_tree(tmp_path):
    (tmp_path / "styles.scss").write_text("body { color: red; }\n")
    with pytest.raises(RuntimeError, match="refusing to report a count"):
        measure([tmp_path])


def test_measure_finds_a_planted_violation(tmp_path):
    (tmp_path / "sale_order.py").write_text(
        textwrap.dedent("""
            class SaleOrder(models.Model):
                _name = "sale.order"

                def _validate_amount(self):
                    pass

                def _parse_amount(self, text):
                    return float(text)
        """)
    )
    found = measure([tmp_path])
    assert [v.name for v in found] == ["_validate_amount"]
    assert found[0].canonical == "_check_"


def test_measure_does_not_count_an_override(tmp_path):
    (tmp_path / "m.py").write_text(
        textwrap.dedent(
            """
            from odoo import models

            class M(models.Model):
                _inherit = "some.model"

                def _validate_leave_request(self):
                    super()._validate_leave_request()
                    return True
            """
        )
    )
    assert measure([tmp_path]) == []


def test_measure_counts_the_same_name_when_it_is_not_an_override(tmp_path):
    (tmp_path / "m.py").write_text(
        textwrap.dedent(
            """
            from odoo import models

            class M(models.Model):
                _name = "some.model"

                def _validate_leave_request(self):
                    return True
            """
        )
    )
    assert [v.name for v in measure([tmp_path])] == ["_validate_leave_request"]


def test_measure_counts_an_override_of_a_DIFFERENT_method(tmp_path):
    (tmp_path / "m.py").write_text(
        textwrap.dedent(
            """
            from odoo import models

            class M(models.Model):
                _inherit = "some.model"

                def _validate_amount(self):
                    return super().write({})
            """
        )
    )
    assert [v.name for v in measure([tmp_path])] == ["_validate_amount"]


def test_measure_skips_test_files(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_sale.py").write_text(
        "class T(models.Model):\n    _name='t'\n    def _validate_x(self): pass\n"
    )
    with pytest.raises(RuntimeError):
        measure([tmp_path])


def test_violation_renders_the_replacement():
    v = Violation(
        path="addons/sale/models/sale_order.py",
        line=12,
        name="_validate_amount",
        verb="validate",
        canonical="_check_",
    )
    assert "_validate_amount" in str(v)
    assert "_check_*" in str(v)


def test_the_real_tree_is_still_scanned():
    # This asserted the checkout still HAD abolished verbs, which stopped being a
    # statement about the gate the moment the sweep reached zero: a ratchet at 0
    # is the goal, not a broken measurement. What has to stay true is that the
    # scan still reaches files -- an empty walk would report 0 for the same
    # reason a clean tree does. The classification itself is covered against a
    # fixture above, and `measure` refusing an empty scan is covered by
    # test_every_gate_refuses_an_empty_tree.
    scanned = _python_files([ROOT / r for r in SCAN_ROOTS])
    assert len(scanned) > 1000, (
        f"only {len(scanned)} files scanned under {', '.join(SCAN_ROOTS)} — the "
        f"walk is broken, and every count it reports would be 0 by accident"
    )
    assert all(p.suffix == ".py" for p in scanned)
    assert all(Path(v.path).suffix == ".py" for v in measure())


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("_get_model_names_in_tree", "head"),
        ("_get_keys_client_only", "head"),
        ("get_view_types_for_window", "head"),
        ("_get_allowed_models", "tail"),
        ("_get_supported_account_types", "tail"),
        ("_get_company_address_field_names", "tail"),
        ("_get_fields_inheriting_views", None),
        ("_get_fields_readable", None),
        ("_get_partner_ids", None),
        ("_compute_xml_id", None),
        ("_sync_path_reservations", None),
    ],
)
def test_collection_head_order_reads_the_position(name, expected):
    assert collection_head_order(name) is expected


def test_collection_head_census_counts_both_orders():
    from naming_vocabulary import census

    c = census()
    assert c.heads_searched > 0
    assert c.heads_head_first > 0
    assert c.heads_tail_first > 0, (
        "the ordering is settled and unapplied outside the fields family; a zero "
        "here means the search stopped matching, not that the tree was converted"
    )


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        (
            "@api.constrains('order', 'field_id')\ndef _check_order(self): pass",
            ["order", "field_id"],
        ),
        ("@constrains('date')\ndef _check_date(self): pass", ["date"]),
        ("def _check_date(self): pass", []),
        ("@api.model\ndef _check_date(self): pass", []),
        ("@api.constrains(*FIELDS)\ndef _check_date(self): pass", []),
        ("@api.onchange('partner_id')\ndef _onchange_partner_id(self): pass", []),
    ],
)
def test_constrains_fields_reads_the_decorator(src, expected):
    from naming_vocabulary import constrains_fields

    node = next(
        n
        for n in ast.walk(ast.parse(textwrap.dedent(src)))
        if isinstance(n, ast.FunctionDef)
    )
    assert constrains_fields(node) == expected


def test_constrains_census_sizes_the_family_it_exempts():
    from naming_vocabulary import census

    c = census()
    assert c.constrains_hooks > 0
    assert c.constrains_single > 0
    assert 0 < c.constrains_named_for_field < c.constrains_single, (
        "a constraint named for its field is the minority the exemption predicts; "
        "0 or all of them means the decorator is no longer being read"
    )
    assert 0 < c.constrains_unruled < c.constrains_hooks - c.constrains_canonical


# §2.4.13's three populations. Each fixture is a real addon layout rather than a
# bare file, because the scope test is `__manifest__.py` above a models/ wizard/
# wizards/ directory and a fixture that skips either half would pass while
# measuring nothing.
HELPERS = """
    def make_widget_vals(record):
        return {}


    class Helper:
        def _fetch_rows(self):
            return []


    class WidgetLine(models.Model):
        _name = "widget.line"

        def _get_lines(self):
            def _retrieve_bucket(key):
                return key

            return _retrieve_bucket
"""


def _addon(tmp_path, subdir="models", manifest=True):
    module = tmp_path / "widget"
    package = module / subdir
    package.mkdir(parents=True)
    if manifest:
        (module / "__manifest__.py").write_text("{'name': 'widget'}\n")
    (package / "widget_line.py").write_text(textwrap.dedent(HELPERS))
    return module


@pytest.mark.parametrize(
    "subdir",
    ["models", "wizard", "wizards", "controllers", "tools", "report", "utils"],
)
def test_an_addon_helper_file_is_governed_in_every_directory(tmp_path, subdir):
    assert governs_module_helpers(_addon(tmp_path, subdir) / subdir / "widget_line.py")


def test_a_helper_directly_under_the_addon_is_governed(tmp_path):
    module = tmp_path / "widget"
    module.mkdir()
    (module / "__manifest__.py").write_text("{'name': 'widget'}\n")
    (module / "utils.py").write_text("def validate_thread(token):\n    pass\n")
    assert governs_module_helpers(module / "utils.py")
    assert [v.name for v in measure([module])] == ["validate_thread"]


def test_a_migration_script_is_governed(tmp_path):
    # §2.4.13 recorded that the two gates answered this differently by
    # mechanism; this pins the decision that a helper in an upgrade script is
    # this repository's code like any other.
    module = _addon(tmp_path, "migrations/1.2")
    assert governs_module_helpers(module / "migrations" / "1.2" / "widget_line.py")


def test_a_vendored_tree_is_skipped_under_its_real_name(tmp_path):
    # `vendored` matched no directory in the workspace; `_vendor` is the spelling
    # `addons/auth_passkey/_vendor` uses, and its WebAuthn verifiers are not ours.
    module = _addon(tmp_path, "_vendor/webauthn")
    assert measure([module]) == []


def test_all_three_uncounted_populations_are_measured(tmp_path):
    found = {v.name for v in measure([_addon(tmp_path)])}
    assert found == {"make_widget_vals", "_fetch_rows", "_retrieve_bucket"}, (
        "§2.4.13 governs a module-level function, a plain-class method and a "
        f"nested def in an addon models/ file; measured {sorted(found)}"
    )


def test_the_census_counts_module_helpers_by_scope_not_by_statement(tmp_path):
    """The same hole, declared a second time in `census()`.

    Free to close today (354 either way) and only free until somebody adds an
    import shim under an addon's `models/`, so it is pinned rather than trusted.
    """
    import ast

    from naming_vocabulary import _module_scope_defs

    tree = ast.parse(
        textwrap.dedent("""
            def plain():
                pass

            try:
                def shimmed():
                    pass
            except ImportError:
                def shimmed():
                    pass
        """)
    )
    by_statement = sum(
        isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) for n in tree.body
    )
    assert by_statement == 1
    assert len(_module_scope_defs(tree)) == 3


@pytest.mark.parametrize(
    "wrapper",
    [
        "try:\n{body}\nexcept ImportError:\n    pass",
        "if CONDITION:\n{body}",
        "with ctx():\n{body}",
    ],
)
def test_a_module_scope_def_inside_a_compound_statement_is_governed(tmp_path, wrapper):
    """`for node in tree.body` was statement-correct; the question is scope."""
    (tmp_path / "__manifest__.py").write_text("{}")
    models = tmp_path / "models"
    models.mkdir()
    (models / "a.py").write_text(
        wrapper.format(body="    def _make_thing():\n        return 1") + "\n"
    )
    assert [v.name for v in measure([tmp_path])] == ["_make_thing"]


def test_the_import_shim_reports_both_definitions(tmp_path):
    """The shape that found the hole: one name defined twice, neither seen."""
    (tmp_path / "__manifest__.py").write_text("{}")
    models = tmp_path / "models"
    models.mkdir()
    (models / "a.py").write_text(
        textwrap.dedent("""
            try:
                def _make_linestring_wkt(coords):
                    return shapely.wkt(coords)
            except ImportError:
                def _make_linestring_wkt(coords):
                    raise NotImplementedError
        """)
    )
    assert [v.name for v in measure([tmp_path])] == [
        "_make_linestring_wkt",
        "_make_linestring_wkt",
    ]


def test_a_def_inside_a_function_inside_a_try_is_still_a_closure(tmp_path):
    """Scope-correct, not depth-correct."""
    (tmp_path / "__manifest__.py").write_text("{}")
    models = tmp_path / "models"
    models.mkdir()
    (models / "a.py").write_text(
        textwrap.dedent("""
            try:
                def outer():
                    def _make_inner():
                        return 1
                    return _make_inner
            except ImportError:
                pass
        """)
    )
    assert sorted(v.name for v in measure([tmp_path])) == ["_make_inner"]


def test_a_method_on_a_class_inside_a_try_is_reached_once(tmp_path):
    (tmp_path / "__manifest__.py").write_text("{}")
    models = tmp_path / "models"
    models.mkdir()
    (models / "a.py").write_text(
        textwrap.dedent("""
            try:
                class Thing(models.Model):
                    _name = "thing"

                    def _make_vals(self):
                        return {}
            except ImportError:
                pass
        """)
    )
    assert [v.name for v in measure([tmp_path])] == ["_make_vals"]


def test_a_definition_is_counted_once_however_deeply_nested(tmp_path):
    module = tmp_path / "widget"
    (module / "models").mkdir(parents=True)
    (module / "__manifest__.py").write_text("{'name': 'widget'}\n")
    (module / "models" / "deep.py").write_text(
        textwrap.dedent("""
            class WidgetLine(models.Model):
                _name = "widget.line"

                def _get_lines(self):
                    def outer():
                        def _retrieve_bucket(key):
                            return key

                        return _retrieve_bucket

                    return outer
        """)
    )
    # `ast.walk` from every function reaches the innermost `def` once per
    # enclosing frame, so this is the assertion that keeps a doubly nested name
    # from being reported twice and inflating the floor.
    assert [v.name for v in measure([module])] == ["_retrieve_bucket"]


def test_a_controller_helper_is_measured(tmp_path):
    # The hole §2.4.13 measured at 243 definitions: a class deriving from
    # http.Controller fails is_model_class, and no directory list named
    # `controllers`, so a route handler was in the population of nothing.
    outside = _addon(tmp_path, "controllers")
    assert {v.name for v in measure([outside])} == {
        "make_widget_vals",
        "_fetch_rows",
        "_retrieve_bucket",
    }


def test_a_models_directory_with_no_manifest_above_it_is_not_an_addon(tmp_path):
    loose = _addon(tmp_path, manifest=False)
    assert not governs_module_helpers(loose / "models" / "widget_line.py")
    assert measure([loose]) == []


def test_the_core_package_keeps_the_narrow_population(tmp_path):
    # `naming_core_vocabulary.py` reads every function under odoo/odoo/ on
    # sharper rules and holds a hard zero with an argued allowlist. Widening
    # this gate over the same tree would ask one question twice and answer it
    # two ways -- `append_paths` being §2.4.13's own example of a name that gate
    # allowlists and this one would report.
    core_file = ROOT / "odoo" / "addons" / "base" / "models" / "ir_asset_paths.py"
    if not core_file.is_file():
        pytest.skip(f"{core_file} has moved; the scope claim needs a new witness")
    assert not governs_module_helpers(core_file)


def test_a_model_method_is_still_counted_without_the_widening(tmp_path):
    # The narrow population is not conditional on the addon test: a model class
    # in a file the widening does not reach is measured exactly as before.
    (tmp_path / "sale_order.py").write_text(
        textwrap.dedent("""
            class SaleOrder(models.Model):
                _name = "sale.order"

                def _validate_amount(self):
                    pass

                def helper():
                    pass
        """)
    )
    assert not governs_module_helpers(tmp_path / "sale_order.py")
    assert [v.name for v in measure([tmp_path])] == ["_validate_amount"]


def test_governed_definitions_reads_a_file_without_measuring_it(tmp_path):
    module = _addon(tmp_path)
    path = module / "models" / "widget_line.py"
    names = [n.name for n in governed_definitions(path, ast.parse(path.read_text()))]
    assert sorted(names) == [
        "_fetch_rows",
        "_get_lines",
        "_retrieve_bucket",
        "make_widget_vals",
    ], (
        "the population is every definition the vocabulary reaches, compliant "
        f"ones included; classify() is what narrows it. Got {sorted(names)}"
    )


@pytest.mark.parametrize(
    ("name", "canonical"),
    [
        ("_prepare_po_get_domain", "_get_domain_"),
        ("_prepare_badges_domain", "_get_domain_"),
        ("_build_search_domain", "_get_domain_"),
    ],
)
def test_a_domain_tail_lands_on_the_domain_row_whatever_verb_assembled_it(
    name, canonical
):
    assert classify(name) == (name.lstrip("_").partition("_")[0], canonical)


@pytest.mark.parametrize(
    "name", ["_get_domain_po", "_prepare_invoice_vals", "_domain_partner_id"]
)
def test_the_domain_row_itself_and_the_payload_row_stay_quiet(name):
    assert classify(name) is None


@pytest.mark.parametrize(
    ("src", "canonical"),
    [
        # fills a dict the caller owns
        (
            "def _prepare_request(self, url, kwargs):\n    kwargs['timeout'] = 10",
            "_update_",
        ),
        # writes fields on the receiver and returns nothing
        (
            "def _get_access_token(self):\n    for link in self:\n        link.access_token = link._fetch()",
            "_update_",
        ),
        # §2.4.11 reserves _resolve_ for an object-or-None
        (
            "def _resolve_partner_to(self, by_res_id, contribution):\n    for k, v in by_res_id.items():\n        contribution[k] = v",
            "_update_",
        ),
        # a bare `return` after the side effect is still no product
        ("def _get_mfa_state(self):\n    self.state = 'done'\n    return", "_update_"),
        # a raise in a branch does not rescue a body that stores
        (
            "def _get_locked(self):\n    if self.bad:\n        raise UserError('x')\n    self.locked = True",
            "_update_",
        ),
        # an ORM write with no store is still the Mutation row
        (
            "def _get_or_create_channel(self):\n    if not self.line:\n        self.env['channel'].create({'a': 1})",
            "_update_",
        ),
    ],
)
def test_a_producer_prefix_on_a_body_with_no_product_is_the_mutation_row(
    src, canonical
):
    node = _fn(src)
    assert (
        producer_without_product(node, ast.Module(body=[node], type_ignores=[]))
        == canonical
    )


def test_a_hook_bound_name_is_left_to_the_field_hook_gate():
    tree = ast.parse(
        textwrap.dedent("""
            class Picking(models.Model):
                count_mo_todo = fields.Integer(compute="_get_mo_count")

                def _get_mo_count(self):
                    for picking in self:
                        picking.count_mo_todo = 1
        """)
    )
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    assert producer_without_product(node, tree) is None


@pytest.mark.parametrize(
    "src",
    [
        # returns a value
        "def _get_lines(self):\n    return self.line_ids",
        # yields
        "def _get_pairs(self, other):\n    yield self, other",
        # a return inside a nested scope does not count, but this one is the outer
        "def _get_total(self):\n    def inner():\n        return 1\n    return inner()",
        # extension stubs: docstring, pass, bare return, check_singleton, raise
        "def _get_signature(self):\n    self.check_singleton()",
        "def _get_mfa_type(self) -> str | None:\n    return",
        "def _prepare_extra(self):\n    pass",
        "def _get_thing(self):\n    raise NotImplementedError",
        # a body whose last statement raises is §2.4.10's question
        "def _get_locked(self):\n    self.locked = True\n    raise UserError('x')",
        # no product and no store: a raise-only validator is §2.4.8's question
        "def _get_checks_error(self):\n    if self.bad:\n        raise UserError('x')",
        # a branch that raises NotImplementedError with an override elsewhere
        "def _get_document_vals(self):\n    self.check_singleton()\n    if self.kind == 'invoice':\n        raise NotImplementedError",
        # calls something, stores nothing, writes no record
        "def _prepare_mails(self):\n    for a in self.ids:\n        self.env['mail'].send(a)",
        # not a producer prefix
        "def _update_kwargs(self, kwargs):\n    kwargs['a'] = 1",
    ],
)
def test_a_product_a_stub_a_raise_and_a_non_producer_are_quiet(src):
    node = _fn(src)
    assert (
        producer_without_product(node, ast.Module(body=[node], type_ignores=[])) is None
    )


def test_a_nested_return_does_not_lend_the_outer_def_a_product():
    node = _fn(
        "def _get_total(self, acc):\n    def inner():\n        return 1\n    acc['total'] = inner()"
    )
    assert (
        producer_without_product(node, ast.Module(body=[node], type_ignores=[]))
        == "_update_"
    )


def test_the_producer_rule_reaches_measure_and_skips_overrides(tmp_path):
    (tmp_path / "__manifest__.py").write_text("{}")
    models = tmp_path / "models"
    models.mkdir()
    (models / "a.py").write_text(
        textwrap.dedent("""
            class Thing(models.Model):
                _name = "thing"

                def _prepare_request(self, kwargs):
                    kwargs["a"] = 1

                def _get_lines(self):
                    super()._get_lines()
                    self.x = 1

                def _prepare_search_domain(self):
                    return []
        """)
    )
    found = measure([tmp_path])
    assert [(v.name, v.verb, v.canonical) for v in found] == [
        ("_prepare_request", "prepare", "_update_"),
        ("_prepare_search_domain", "prepare", "_get_domain_"),
    ]
