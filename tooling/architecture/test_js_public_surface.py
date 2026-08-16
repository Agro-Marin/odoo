import js_public_surface as jps
import pytest


def _consumer(root, name, body):
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return root


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
    _consumer(
        tmp_path,
        "mail/static/tests/a.js",
        'import { x } from "@web/../tests/web_test_helpers";\n',
    )
    assert jps.measure((tmp_path,)) == {}


def test_type_only_references_are_not_surface(tmp_path):
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


def test_provenance_records_the_importing_scope_by_name(tmp_path):
    ent = tmp_path / "enterprise"
    _consumer(ent, "sale/static/src/a.js", 'import "@web/core/registry";\n')
    detailed = jps.measure_detailed((("enterprise", ent),))
    assert detailed == {"@web/core/registry": {"enterprise": (1, 0)}}
    assert jps.provenance(detailed) == {"@web/core/registry": frozenset({"enterprise"})}


def test_a_bare_path_scope_takes_its_directory_name(tmp_path):
    root = tmp_path / "agromarin"
    _consumer(root, "geo/static/src/a.js", 'import "@web/core/registry";\n')
    assert jps.provenance(jps.measure_detailed((root,))) == {
        "@web/core/registry": frozenset({"agromarin"})
    }


def test_one_specifier_reached_from_two_scopes_carries_both(tmp_path):
    a, b = tmp_path / "odoo", tmp_path / "enterprise"
    _consumer(a, "mail/static/src/a.js", 'import "@web/core/registry";\n')
    _consumer(b, "sale/static/src/b.js", 'import "@web/core/registry";\n')
    detailed = jps.measure_detailed((("odoo", a), ("enterprise", b)))
    assert jps.provenance(detailed) == {
        "@web/core/registry": frozenset({"odoo", "enterprise"})
    }


def test_an_absent_scope_contributes_nothing_and_is_not_invented(tmp_path):
    present = tmp_path / "odoo"
    _consumer(present, "mail/static/src/a.js", 'import "@web/core/registry";\n')
    detailed = jps.measure_detailed(
        (("odoo", present), ("enterprise", tmp_path / "not-there"))
    )
    assert detailed == {"@web/core/registry": {"odoo": (1, 0)}}


def test_growth_and_shrink_fail_per_scope():
    measured = {"@web/a": frozenset({"odoo"}), "@web/b": frozenset({"odoo"})}
    pinned = {"@web/b": frozenset({"odoo"}), "@web/c": frozenset({"odoo"})}
    new, gone = jps.drift(measured, pinned, ["odoo"])
    assert new == {"odoo": ["@web/a"]}
    assert gone == {"odoo": ["@web/c"]}


def test_a_scope_not_present_is_not_judged():
    measured = {"@web/a": frozenset({"odoo"})}
    pinned = {"@web/a": frozenset({"odoo"}), "@web/b": frozenset({"enterprise"})}
    new, gone = jps.drift(measured, pinned, ["odoo"])
    assert (new, gone) == ({}, {})


def test_the_full_workspace_judges_every_scope():
    measured = {"@web/a": frozenset({"odoo"})}
    pinned = {"@web/a": frozenset({"odoo"}), "@web/b": frozenset({"enterprise"})}
    new, gone = jps.drift(measured, pinned, ["odoo", "enterprise"])
    assert new == {}
    assert gone == {"enterprise": ["@web/b"]}


def test_an_import_from_a_new_scope_is_growth_there():
    measured = {"@web/a": frozenset({"enterprise", "agromarin"})}
    pinned = {"@web/a": frozenset({"enterprise"})}
    new, gone = jps.drift(measured, pinned, ["enterprise", "agromarin"])
    assert new == {"agromarin": ["@web/a"]}
    assert gone == {}


def test_a_legacy_tagless_pin_applies_to_every_scope():
    measured = {"@web/a": frozenset({"odoo"})}
    pinned = {"@web/a": frozenset()}
    new, gone = jps.drift(measured, pinned, ["odoo", "enterprise"])
    assert new == {}
    assert gone == {"enterprise": ["@web/a"]}


def test_comments_and_blanks_are_not_pins(tmp_path, monkeypatch):
    pin = tmp_path / "pin.txt"
    pin.write_text("# c\n\n@web/core/registry  odoo enterprise\n")
    monkeypatch.setattr(jps, "PINNED", pin)
    assert jps.load_pinned() == {
        "@web/core/registry": frozenset({"odoo", "enterprise"})
    }


def test_a_tagless_line_loads_as_pinned_everywhere(tmp_path, monkeypatch):
    pin = tmp_path / "pin.txt"
    pin.write_text("@web/core/registry\n")
    monkeypatch.setattr(jps, "PINNED", pin)
    assert jps.load_pinned() == {"@web/core/registry": frozenset()}


def test_update_writes_the_measured_surface_sorted_with_provenance(
    tmp_path, monkeypatch
):
    pin = tmp_path / "pin.txt"
    monkeypatch.setattr(jps, "PINNED", pin)
    jps.write_pinned(
        {
            "@web/b": frozenset({"enterprise", "odoo"}),
            "@web/a": frozenset({"agromarin"}),
        }
    )
    assert jps.load_pinned() == {
        "@web/a": frozenset({"agromarin"}),
        "@web/b": frozenset({"odoo", "enterprise"}),
    }
    body = [
        line
        for line in pin.read_text().splitlines()
        if line and not line.startswith("#")
    ]
    assert body == ["@web/a  agromarin", "@web/b  odoo enterprise"]


def test_update_refuses_a_partial_checkout(tmp_path, monkeypatch):
    present = tmp_path / "odoo"
    _consumer(present, "mail/static/src/a.js", 'import "@web/core/registry";\n')
    monkeypatch.setattr(
        jps,
        "CONSUMER_ROOTS",
        (("odoo", present), ("enterprise", tmp_path / "not-there")),
    )
    with pytest.raises(SystemExit) as exc:
        jps.main(["--update"])
    assert exc.value.code == 2


def test_real_surface_is_measured_and_matches_its_pin():
    detailed = jps.measure_detailed()
    assert len(detailed) > 100, "expected the real consumer tree to be found"
    assert "@web/core/registry" in detailed, "the most-imported specifier is missing"
    pinned = jps.load_pinned()
    assert pinned, "no pin file — the ratchet would pass against nothing"
    present = [name for name, _ in jps._named_roots(jps.CONSUMER_ROOTS)]
    assert "odoo" in present, "the gate's own checkout must always be a scope"
    new, gone = jps.drift(jps.provenance(detailed), pinned, present)
    assert (new, gone) == ({}, {}), (
        f"surface drift in scopes {sorted(set(new) | set(gone))}: "
        f"{ {s: v[:5] for s, v in new.items()} } new, "
        f"{ {s: v[:5] for s, v in gone.items()} } gone"
    )


def test_the_surface_is_mostly_deep_which_is_why_this_exists():
    measured = jps.measure()
    deep = sum(1 for s in measured if s.count("/") >= 3)
    assert deep > len(measured) // 2, (
        f"only {deep} of {len(measured)} specifiers are 3+ segments deep — if "
        "that has changed, the argument in this gate's docstring has too"
    )


def test_a_test_only_consumer_is_counted_apart_but_still_pinned(tmp_path):
    _consumer(tmp_path, "mail/static/tests/a.js", 'import "@web/webclient/clickbot";\n')
    assert jps.measure_by_scope((tmp_path,)) == {"@web/webclient/clickbot": (0, 1)}
    assert jps.measure((tmp_path,)) == {"@web/webclient/clickbot": 1}


def test_production_and_test_importers_of_one_specifier_are_split(tmp_path):
    _consumer(tmp_path, "mail/static/src/a.js", 'import "@web/core/registry";\n')
    _consumer(tmp_path, "mail/static/tests/b.js", 'import "@web/core/registry";\n')
    assert jps.measure_by_scope((tmp_path,)) == {"@web/core/registry": (1, 1)}


def test_the_real_surface_is_overwhelmingly_production():
    by_scope = jps.measure_by_scope()
    test_only = [s for s, (prod, test) in by_scope.items() if prod == 0 and test]
    assert len(test_only) < len(by_scope) // 10, (
        f"{len(test_only)} of {len(by_scope)} specifiers are reached only by tests"
    )


def _web(root, *paths):
    for p in paths:
        f = root / "static" / "src" / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("export const x = 1;\n")
    return root


def test_a_specifier_backed_by_a_file_resolves(tmp_path, monkeypatch):
    monkeypatch.setattr(jps, "WEB", _web(tmp_path, "core/user.js"))
    assert jps.unresolved(["@web/core/user"]) == []


def test_a_specifier_backed_by_a_face_resolves(tmp_path, monkeypatch):
    monkeypatch.setattr(jps, "WEB", _web(tmp_path, "components/barcode/index.js"))
    assert jps.unresolved(["@web/components/barcode"]) == []


def test_a_specifier_backed_by_nothing_is_unresolved(tmp_path, monkeypatch):
    monkeypatch.setattr(jps, "WEB", _web(tmp_path, "core/user.js"))
    assert jps.unresolved(["@web/services/user"]) == ["@web/services/user"]


def test_a_directory_without_a_face_does_not_resolve(tmp_path, monkeypatch):
    root = _web(tmp_path, "core/utils/dnd.js")
    monkeypatch.setattr(jps, "WEB", root)
    assert jps.unresolved(["@web/core/utils"]) == ["@web/core/utils"]


def test_every_known_unresolved_entry_really_dangles():
    assert jps.unresolved(jps.KNOWN_UNRESOLVED) == sorted(jps.KNOWN_UNRESOLVED), (
        "an entry in KNOWN_UNRESOLVED now resolves — shrink the set"
    )


def test_the_real_surface_carries_no_unaccounted_dangling_specifier():
    measured = jps.measure()
    assert set(jps.unresolved(measured)) <= jps.KNOWN_UNRESOLVED, (
        "a specifier imported from outside web resolves to no module in it"
    )


def test_mail_is_governed_and_its_pin_matches_the_measured_surface():
    assert "mail" in jps.GOVERNED_ADDONS
    detailed = jps.measure_detailed(jps.CONSUMER_ROOTS, "mail")
    assert len(detailed) > 50, "expected the real consumer tree to be found"
    assert "@mail/core/common/record" in detailed, (
        "the model layer's entry point is imported from outside mail and must "
        "be measured"
    )
    pinned = jps.load_pinned("mail")
    assert pinned, "no mail pin file — the ratchet would pass against nothing"
    present = [name for name, _ in jps._named_roots(jps.CONSUMER_ROOTS)]
    new, gone = jps.drift(jps.provenance(detailed), pinned, present)
    assert (new, gone) == ({}, {}), (
        f"mail surface drift in scopes {sorted(set(new) | set(gone))}: "
        f"{ {s: v[:5] for s, v in new.items()} } new, "
        f"{ {s: v[:5] for s, v in gone.items()} } gone"
    )


def test_the_two_addons_do_not_share_a_pin_file():
    assert jps.pin_path("web") != jps.pin_path("mail")
    assert jps.pin_path("web").name == "public_surface_web.txt"
    assert jps.pin_path("mail").name == "public_surface_mail.txt"


def test_mails_shallow_surface_is_exactly_the_unlayered_directory():

    measured = jps.measure(jps.CONSUMER_ROOTS, "mail")
    shallow = sorted(s for s in measured if s.count("/") < 3)
    assert shallow == [
        "@mail/model/export",
        "@mail/model/misc",
        "@mail/model/record",
    ]


def test_mails_deep_and_production_specifiers_are_different_sets():

    detailed = jps.measure_detailed(jps.CONSUMER_ROOTS, "mail")
    deep = {s for s in detailed if s.count("/") >= 3}
    production = {
        s for s, scopes in detailed.items() if any(prod for prod, _ in scopes.values())
    }
    assert deep != production
    assert deep - production, "some deep specifiers are reached only from tests"


def test_an_addons_own_imports_are_not_its_surface():
    assert jps._is_addon_internal(
        jps.ROOT / "addons" / "mail" / "static" / "src" / "x.js", "mail"
    )
    assert not jps._is_addon_internal(
        jps.ROOT / "addons" / "web" / "static" / "src" / "x.js", "mail"
    )
