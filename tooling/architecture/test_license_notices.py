import license_notices as ln


def _tree(tmp_path, files):
    for rel, body in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf8")
    return tmp_path


MIT = (
    "/* Copyright (c) 2013 Someone\n\nPermission is hereby granted, free of charge */\n"
)
APACHE = "# Licensed under the Apache License, Version 2.0\n"


def test_an_intact_notice_is_not_a_finding(monkeypatch, tmp_path):
    root = _tree(tmp_path, {"a/vendored.js": MIT + "export const x = 1;\n"})
    monkeypatch.setattr(ln, "PINNED", {"a/vendored.js": 1})
    assert ln.measure(root) == []


def test_a_removed_notice_is_a_finding(monkeypatch, tmp_path):
    """The defect this gate exists for: a comment strip eats the notice.

    Byte-identical minification passes over exactly this, because a license
    notice IS a comment and the strip really did only move comments.
    """
    root = _tree(tmp_path, {"a/vendored.js": "export const x = 1;\n"})
    monkeypatch.setattr(ln, "PINNED", {"a/vendored.js": 1})
    assert [(f.path, f.expected, f.found) for f in ln.measure(root)] == [
        ("a/vendored.js", 1, 0)
    ]


def test_losing_one_of_two_notices_is_a_finding(monkeypatch, tmp_path):
    """html-to-image.js carries two; a partial strip must not read as intact."""
    root = _tree(tmp_path, {"a/two.js": MIT})
    monkeypatch.setattr(ln, "PINNED", {"a/two.js": 2})
    assert [f.found for f in ln.measure(root)] == [1]


def test_a_deleted_file_is_a_finding_not_a_pass(monkeypatch, tmp_path):
    root = _tree(tmp_path, {"other.js": "//\n"})
    monkeypatch.setattr(ln, "PINNED", {"a/gone.js": 1})
    assert [f.found for f in ln.measure(root)] == [-1]


def test_both_licence_families_are_recognised(monkeypatch, tmp_path):
    root = _tree(tmp_path, {"a/mit.js": MIT, "b/apache.py": APACHE})
    monkeypatch.setattr(ln, "PINNED", {"a/mit.js": 1, "b/apache.py": 1})
    assert ln.measure(root) == []


def test_extra_notices_are_not_a_finding(monkeypatch, tmp_path):
    """Only a DROP matters. Gaining one is someone vendoring more code."""
    root = _tree(tmp_path, {"a/two.js": MIT + MIT})
    monkeypatch.setattr(ln, "PINNED", {"a/two.js": 1})
    assert ln.measure(root) == []


def test_the_real_pin_list_is_not_empty_and_resolves(monkeypatch):
    """A gate pinning nothing, or pinning paths that moved, protects nothing."""
    assert ln.PINNED, "an empty pin list passes over everything"
    for rel in ln.PINNED:
        assert (ln.ROOT / rel).is_file(), f"{rel} is pinned but not in the tree"


def test_the_tree_is_currently_intact(monkeypatch):
    assert ln.measure() == [], "a pinned license notice has been lost"
