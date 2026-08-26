import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import doc_measured
import translation_catalog as tcat


def _module(root, name, *, pot, sources):
    module_dir = root / "addons" / name
    (module_dir / "i18n").mkdir(parents=True)
    (module_dir / "i18n" / f"{name}.pot").write_text(pot, encoding="utf-8")
    for rel, text in sources.items():
        target = module_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return (root / "odoo" / "addons", root / "addons")


def _pot(*msgids):
    return "\n\n".join(f'msgid "{m}"\nmsgstr ""' for m in msgids) + "\n"


def test_a_string_the_catalogue_carries_is_resolved(tmp_path):
    roots = _module(
        tmp_path,
        "alpha",
        pot=_pot("Dear Sender"),
        sources={"models/thing.py": 'x = _("Dear Sender")\n'},
    )
    found, stats = tcat.measure(roots)
    assert found == []
    assert stats == {"modules": 1, "strings": 1, "unresolved": 0}


def test_a_reflowed_literal_is_reported(tmp_path):
    roots = _module(
        tmp_path,
        "alpha",
        pot='msgid ""\n"The message below could not be accepted by the address %"\n'
        '"(name)s.\\n"\n"                 Only followers may write."\nmsgstr ""\n',
        sources={
            "models/thing.py": 'x = _(\n    "The message below could not be accepted '
            'by the address %(name)s. "\n    "Only followers may write."\n)\n'
        },
    )
    found, _stats = tcat.measure(roots)
    assert len(found) == 1
    assert found[0].module == "alpha"
    assert found[0].line == 1, "the call site, not the continuation line"


def test_a_multiline_msgid_is_read_back_verbatim(tmp_path):
    roots = _module(
        tmp_path,
        "alpha",
        pot='msgid ""\n"one "\n"two "\n"three"\nmsgstr ""\n',
        sources={"models/thing.py": 'x = _("one two three")\n'},
    )
    found, stats = tcat.measure(roots)
    assert found == [], "the joined msgid must equal the source literal"
    assert stats["strings"] == 1


def test_gettext_on_an_environment_counts_too(tmp_path):
    roots = _module(
        tmp_path,
        "alpha",
        pot=_pot("known"),
        sources={
            "models/thing.py": 'a = self.env._("known")\nb = self.env._("other")\n'
        },
    )
    found, stats = tcat.measure(roots)
    assert stats["strings"] == 2
    assert [f.source for f in found] == ["other"]


def test_non_constant_arguments_are_out_of_scope(tmp_path):
    roots = _module(
        tmp_path,
        "alpha",
        pot=_pot(),
        sources={"models/thing.py": 'a = _(f"hi {x}")\nb = _(msg)\nc = _()\n'},
    )
    found, stats = tcat.measure(roots)
    assert found == []
    assert stats["strings"] == 0


def test_tests_are_excluded(tmp_path):
    roots = _module(
        tmp_path,
        "alpha",
        pot=_pot(),
        sources={
            "tests/test_thing.py": 'x = _("only in a test")\n',
            "test_helper.py": 'y = _("also scaffolding")\n',
        },
    )
    found, stats = tcat.measure(roots)
    assert found == []
    assert stats["strings"] == 0


def test_a_module_without_a_catalogue_is_skipped_not_counted(tmp_path):
    roots = _module(tmp_path, "alpha", pot=_pot("known"), sources={})
    bare = tmp_path / "addons" / "beta"
    (bare / "models").mkdir(parents=True)
    (bare / "models" / "thing.py").write_text('x = _("never exported")\n')
    found, stats = tcat.measure(roots)
    assert found == []
    assert stats["modules"] == 1


def test_an_empty_tree_is_refused(tmp_path):
    (tmp_path / "addons").mkdir()
    (tmp_path / "odoo" / "addons").mkdir(parents=True)
    with pytest.raises(RuntimeError, match="refusing to report a clean zero"):
        tcat.measure((tmp_path / "odoo" / "addons", tmp_path / "addons"))


def test_the_docstring_measurement_is_fresh():
    _found, stats = tcat.measure()
    problems = doc_measured.check(pathlib.Path(tcat.__file__), stats)
    assert not problems, (
        "stale MEASURED block:\n  "
        + "\n  ".join(problems)
        + "\n\n  python tooling/architecture/translation_catalog.py --update-doc"
    )


def _po(root, module, lang, pairs):
    path = root / "addons" / module / "i18n" / f"{lang}.po"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n\n".join(f'msgid "{k}"\nmsgstr "{v}"' for k, v in pairs.items())
    path.write_text(body + "\n", encoding="utf-8")


def test_read_translations_joins_continuation_lines():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        po = pathlib.Path(tmp) / "fr.po"
        po.write_text(
            'msgid ""\n"one "\n"two"\nmsgstr ""\n"un "\n"deux"\n\n'
            'msgid "empty"\nmsgstr ""\n',
            encoding="utf-8",
        )
        pairs = tcat.read_translations(po)
    assert pairs["one two"] == "un deux"
    assert pairs["empty"] == ""


def test_a_rewording_reports_what_it_strands(tmp_path):
    roots = _module(
        tmp_path,
        "alpha",
        pot=_pot("Rendering supports only qweb and inline_template; got %(engine)s."),
        sources={
            "models/thing.py": 'x = _("Rendering supports only %(engines)s; got %(engine)s.")\n'
        },
    )
    old = "Rendering supports only qweb and inline_template; got %(engine)s."
    _po(tmp_path, "alpha", "fr", {old: "Le rendu ne supporte que…"})
    _po(tmp_path, "alpha", "de", {old: "Rendering unterstützt nur…"})
    _po(tmp_path, "alpha", "it", {old: ""})

    found, _stats = tcat.measure(roots)
    assert len(found) == 1
    cost = tcat.reword_cost(
        found[0].source,
        tmp_path / "addons" / "alpha",
        tcat.read_msgids(tmp_path / "addons" / "alpha" / "i18n" / "alpha.pot"),
    )
    assert cost is not None
    assert cost.previous == old
    assert cost.translated == 2, "the empty msgstr is not a translation"
    assert cost.catalogues == 3
    assert sorted(cost.languages) == ["de", "fr"]


def test_a_genuinely_new_string_costs_nothing(tmp_path):
    roots = _module(
        tmp_path,
        "alpha",
        pot=_pot("Something else entirely about invoices"),
        sources={"models/thing.py": 'x = _("Cannot render %(label)s: not a model.")\n'},
    )
    _po(tmp_path, "alpha", "fr", {"Something else entirely about invoices": "…"})
    found, _stats = tcat.measure(roots)
    cost = tcat.reword_cost(
        found[0].source,
        tmp_path / "addons" / "alpha",
        tcat.read_msgids(tmp_path / "addons" / "alpha" / "i18n" / "alpha.pot"),
    )
    assert cost is None, "no near neighbour means nothing is displaced"


def test_a_near_neighbour_nobody_translated_strands_nothing(tmp_path):
    roots = _module(
        tmp_path,
        "alpha",
        pot=_pot("Rendering supports only qweb and inline_template; got %(engine)s."),
        sources={
            "models/thing.py": 'x = _("Rendering supports only %(engines)s; got %(engine)s.")\n'
        },
    )
    _po(tmp_path, "alpha", "fr", {"unrelated": "sans rapport"})
    found, _stats = tcat.measure(roots)
    cost = tcat.reword_cost(
        found[0].source,
        tmp_path / "addons" / "alpha",
        tcat.read_msgids(tmp_path / "addons" / "alpha" / "i18n" / "alpha.pot"),
    )
    assert cost is not None and cost.translated == 0
