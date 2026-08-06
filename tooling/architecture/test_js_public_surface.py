"""Tests for the JS public-surface ratchet.

Stdlib + pytest only — no Odoo imports — so this runs in the same
database-free way as the checker itself. Run with:

    pytest tooling/architecture/test_js_public_surface.py

The measurement tests build synthetic consumer trees, so they keep their
meaning as the real surface shrinks. The two that read the real tree assert
what a measurement gate silently loses: that it found its inputs, and that the
pin it is judging against is the tree's own.
"""

import js_public_surface as jps  # sys.path set by conftest.py


def _consumer(root, name, body):
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return root


# --- what counts as surface ---


def test_an_import_from_outside_web_is_surface(tmp_path):
    _consumer(
        tmp_path, "mail/static/src/x.js", 'import { a } from "@web/core/registry";\n'
    )
    assert jps.measure((tmp_path,)) == {"@web/core/registry": 1}


def test_the_same_specifier_from_two_files_counts_importers(tmp_path):
    _consumer(tmp_path, "mail/static/src/a.js", 'import "@web/core/registry";\n')
    _consumer(tmp_path, "sale/static/src/b.js", 'import "@web/core/registry";\n')
    assert jps.measure((tmp_path,)) == {"@web/core/registry": 2}


def test_a_specifier_named_twice_in_one_file_counts_once(tmp_path):
    _consumer(
        tmp_path,
        "mail/static/src/a.js",
        'import { a } from "@web/core/registry";\nimport { b } from "@web/core/registry";\n',
    )
    assert jps.measure((tmp_path,)) == {"@web/core/registry": 1}


def test_the_test_helper_escape_hatch_is_not_surface(tmp_path):
    # `@web/../tests/...` is how other addons reach web's test helpers. It is
    # documented, and counting it would put the whole test tree on the list.
    _consumer(
        tmp_path,
        "mail/static/tests/a.js",
        'import { x } from "@web/../tests/web_test_helpers";\n',
    )
    assert jps.measure((tmp_path,)) == {}


def test_type_only_references_are_not_surface(tmp_path):
    # A JSDoc @import names a module without depending on it. Moving the file
    # breaks the *type*, which the typecheck locks own; it is not exposure.
    _consumer(
        tmp_path,
        "mail/static/src/a.js",
        '/** @import { X } from "@web/core/registry" */\nexport const y = 1;\n',
    )
    assert jps.measure((tmp_path,)) == {}


def test_vendored_and_node_modules_are_skipped(tmp_path):
    _consumer(tmp_path, "mail/static/lib/dep.js", 'import "@web/core/registry";\n')
    _consumer(tmp_path, "node_modules/pkg/i.js", 'import "@web/core/registry";\n')
    assert jps.measure((tmp_path,)) == {}


# --- the contract ---


def test_a_new_specifier_is_growth_and_a_missing_one_is_a_win():
    # Both directions matter and they fail for different reasons: growth is new
    # exposure, and a pinned specifier no longer imported is surface that was
    # given up and must be recorded, or it can be re-spent for free.
    measured = {"@web/a": 1, "@web/b": 1}
    pinned = {"@web/b", "@web/c"}
    assert sorted(set(measured) - pinned) == ["@web/a"]
    assert sorted(pinned - set(measured)) == ["@web/c"]


# --- the pin file ---


def test_comments_and_blanks_are_not_pins(tmp_path, monkeypatch):
    pin = tmp_path / "pin.txt"
    pin.write_text("# c\n\n@web/core/registry\n")
    monkeypatch.setattr(jps, "PINNED", pin)
    assert jps.load_pinned() == {"@web/core/registry"}


def test_update_writes_the_measured_surface_sorted(tmp_path, monkeypatch):
    # Membership only: nothing this tool can measure decides a tier, so it
    # records none. A fan-in threshold used to invent per-specifier tiers here
    # and was retracted: two importers is equally what a niche-but-public
    # component looks like, so the count cannot decide.
    pin = tmp_path / "pin.txt"
    monkeypatch.setattr(jps, "PINNED", pin)
    jps.write_pinned({"@web/b": 3, "@web/a": 1})
    assert jps.load_pinned() == {"@web/a", "@web/b"}
    body = [
        line
        for line in pin.read_text().splitlines()
        if line and not line.startswith("#")
    ]
    assert body == ["@web/a", "@web/b"]


# --- the gate must actually reach the real tree ---


def test_real_surface_is_measured_and_matches_its_pin():
    measured = jps.measure()
    assert len(measured) > 100, "expected the real consumer tree to be found"
    assert "@web/core/registry" in measured, "the most-imported specifier is missing"
    pinned = jps.load_pinned()
    assert pinned, "no pin file — the ratchet would pass against nothing"
    assert set(measured) == pinned, (
        f"surface drift: {sorted(set(measured) - pinned)[:5]} new, "
        f"{sorted(pinned - set(measured))[:5]} gone"
    )


def test_the_surface_is_mostly_deep_which_is_why_this_exists():
    # The pin is not the interesting number; the depth is. A surface that is
    # mostly layer-edge imports would need no boundary drawn. This one reaches
    # into module internals, which is what makes every internal move expensive.
    measured = jps.measure()
    deep = sum(1 for s in measured if s.count("/") >= 3)
    assert deep > len(measured) // 2, (
        f"only {deep} of {len(measured)} specifiers are 3+ segments deep — if "
        "that has changed, the argument in this gate's docstring has too"
    )


# --- production vs test consumers ---


def test_a_test_only_consumer_is_counted_apart_but_still_pinned(tmp_path):
    # Still surface: moving the file breaks that suite. Counted apart because
    # "only a test reaches this" is not an API decision the way a production
    # importer is.
    _consumer(tmp_path, "mail/static/tests/a.js", 'import "@web/webclient/clickbot";\n')
    assert jps.measure_by_scope((tmp_path,)) == {"@web/webclient/clickbot": (0, 1)}
    assert jps.measure((tmp_path,)) == {"@web/webclient/clickbot": 1}


def test_production_and_test_importers_of_one_specifier_are_split(tmp_path):
    _consumer(tmp_path, "mail/static/src/a.js", 'import "@web/core/registry";\n')
    _consumer(tmp_path, "mail/static/tests/b.js", 'import "@web/core/registry";\n')
    assert jps.measure_by_scope((tmp_path,)) == {"@web/core/registry": (1, 1)}


def test_the_real_surface_is_overwhelmingly_production():
    # If this inverted, the list would be describing what tests poke at rather
    # than what web owes other modules, and the boundary work would follow the
    # wrong signal.
    by_scope = jps.measure_by_scope()
    test_only = [s for s, (prod, test) in by_scope.items() if prod == 0 and test]
    assert len(test_only) < len(by_scope) // 10, (
        f"{len(test_only)} of {len(by_scope)} specifiers are reached only by tests"
    )
