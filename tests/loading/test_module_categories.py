from unittest.mock import MagicMock

import pytest

from odoo.modules import db as modules_db


@pytest.fixture
def cr():
    existing: dict[str, int] = {}
    inserted: list[tuple] = []
    next_id = [100]
    state: dict = {}

    def execute(sql, params=()):
        if "SELECT res_id FROM ir_model_data" in sql:
            xml_id = params[0]
            state["result"] = (existing[xml_id],) if xml_id in existing else None
        elif "INSERT INTO ir_module_category" in sql:
            next_id[0] += 1
            state["result"] = (next_id[0],)
            inserted.append(("category", params[0], params[1], next_id[0]))
        elif "INSERT INTO ir_model_data" in sql:
            existing[params[1]] = params[2]
            inserted.append(("xmlid", params[1], params[2]))
        else:
            state["result"] = None

    cursor = MagicMock()
    cursor.execute.side_effect = execute
    cursor.fetchone.side_effect = lambda: state.get("result")
    cursor.existing = existing
    cursor.inserted = inserted
    return cursor


def _xmlids(cr):
    return [name for kind, name, *_ in cr.inserted if kind == "xmlid"]


class TestDerivedXmlIds:
    def test_a_single_category(self, cr):
        modules_db.create_categories(cr, ["Accounting"])
        assert _xmlids(cr) == ["module_category_accounting"]

    def test_a_nested_category_accumulates_the_whole_path(self, cr):
        modules_db.create_categories(cr, ["Accounting", "Accounting"])
        assert _xmlids(cr) == [
            "module_category_accounting",
            "module_category_accounting_accounting",
        ], (
            "base/data/ir_module_module.xml references "
            "base.module_category_accounting_accounting; the leaf xmlid is the "
            "whole path, not the last segment"
        )

    def test_spaces_become_underscores(self, cr):
        modules_db.create_categories(cr, ["Human Resources"])
        assert _xmlids(cr) == ["module_category_human_resources"]

    def test_an_ampersand_becomes_the_word_and(self, cr):
        modules_db.create_categories(cr, ["Sales & CRM"])
        assert _xmlids(cr) == ["module_category_sales_and_crm"], (
            "an `&` left in place makes an xmlid the XML parser cannot "
            "reference, and every `ref=` to that category silently misses"
        )

    def test_the_replacements_apply_at_every_level(self, cr):
        modules_db.create_categories(cr, ["Sales & CRM", "Lead Generation"])
        assert _xmlids(cr) == [
            "module_category_sales_and_crm",
            "module_category_sales_and_crm_lead_generation",
        ]

    def test_case_is_folded(self, cr):
        modules_db.create_categories(cr, ["ACCOUNTING"])
        assert _xmlids(cr) == ["module_category_accounting"]


class TestParentChaining:
    def test_the_leaf_id_is_returned(self, cr):
        leaf = modules_db.create_categories(cr, ["A", "B"])
        assert leaf == cr.existing["module_category_a_b"]

    def test_each_level_is_the_next_ones_parent(self, cr):
        modules_db.create_categories(cr, ["A", "B", "C"])
        created = [row for row in cr.inserted if row[0] == "category"]
        parents = [row[2] for row in created]
        ids = [row[3] for row in created]
        assert parents == [None, ids[0], ids[1]], (
            "a flat hierarchy puts every category at the top level of the "
            "Apps menu instead of nesting them"
        )

    def test_an_empty_path_creates_nothing(self, cr):
        assert modules_db.create_categories(cr, []) is None
        assert cr.inserted == []


class TestReuseAndCache:
    def test_an_existing_category_is_not_created_twice(self, cr):
        modules_db.create_categories(cr, ["A", "B"])
        cr.inserted.clear()
        leaf = modules_db.create_categories(cr, ["A", "B"])
        assert cr.inserted == [], "a second module in the same category reuses it"
        assert leaf == cr.existing["module_category_a_b"]

    def test_a_sibling_reuses_the_shared_parent(self, cr):
        modules_db.create_categories(cr, ["A", "B"])
        cr.inserted.clear()
        modules_db.create_categories(cr, ["A", "C"])
        assert _xmlids(cr) == ["module_category_a_c"], "only the new leaf"

    def test_the_cache_short_circuits_the_lookup_entirely(self, cr):
        cache: dict[str, int] = {}
        modules_db.create_categories(cr, ["A", "B"], cache)
        assert set(cache) == {"module_category_a", "module_category_a_b"}
        before = cr.execute.call_count
        leaf = modules_db.create_categories(cr, ["A", "B"], cache)
        assert cr.execute.call_count == before, (
            "initialize() calls this once per module against the same handful "
            "of categories; without the cache that is two queries per level "
            "per module on every fresh database"
        )
        assert leaf == cache["module_category_a_b"]

    def test_the_cache_still_returns_the_right_leaf_for_a_new_branch(self, cr):
        cache: dict[str, int] = {}
        modules_db.create_categories(cr, ["A", "B"], cache)
        leaf = modules_db.create_categories(cr, ["A", "C"], cache)
        assert leaf == cache["module_category_a_c"]
        assert leaf != cache["module_category_a_b"]

    def test_without_a_cache_it_still_works_through_the_database(self, cr):
        modules_db.create_categories(cr, ["A"], None)
        leaf = modules_db.create_categories(cr, ["A"], None)
        assert leaf == cr.existing["module_category_a"]
