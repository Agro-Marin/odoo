"""Drift guard for the hand-inlined field-ACL preamble.

The read-access check ``not (not self.groups or env.su or
record._has_field_access(self, "read"))`` is inlined into every hot ``__get__``
path instead of calling one helper, for speed. Nothing else keeps the copies in
sync, so a change to field-access semantics (e.g. a new "read" vs "export"
distinction) must touch all of them or silently diverge. This test pins the
canonical form and the exact set of sites, so adding, removing, or altering one
fails here. Mirrors ``test_scalar_fastpath_lambda_matches_convert_to_record``
for the conversion lambdas. Pure source scan -- no import, no database.
"""

import pathlib

_FIELDS_DIR = pathlib.Path(__file__).resolve().parent.parent / "fields"

# canonical preamble, modulo the singleton/recordset variable name
_CANONICAL = 'not (not self.groups or env.su or {rec}._has_field_access(self, "read"))'
_ALLOWED = {_CANONICAL.format(rec="record"), _CANONICAL.format(rec="records")}

# every site is expected to use the canonical form; update deliberately if the
# ACL semantics change (and change ALL sites together).
_EXPECTED_SITES = {
    ("base.py", 3),
    ("textual.py", 2),  # BaseString.__get__ + Html.__get__ (en_US fallback path)
    ("relational/many2one.py", 1),
    ("relational/_base.py", 1),
}


def _iter_access_lines():
    for path in sorted(_FIELDS_DIR.rglob("*.py")):
        rel = path.relative_to(_FIELDS_DIR).as_posix()
        for line in path.read_text().splitlines():
            if "_has_field_access(self," in line:
                yield rel, line.strip()


def _has_canonical_preamble(line: str) -> bool:
    return any(form in line for form in _ALLOWED)


def test_every_field_access_check_uses_the_canonical_preamble():
    for rel, line in _iter_access_lines():
        # only the read-access preamble is guarded here
        if '_has_field_access(self, "read")' not in line:
            continue
        assert _has_canonical_preamble(line), (
            f"divergent field-ACL preamble in {rel}: {line!r}"
        )


def test_field_access_preamble_site_set_is_unchanged():
    counts: dict[str, int] = {}
    for rel, line in _iter_access_lines():
        if _has_canonical_preamble(line):
            counts[rel] = counts.get(rel, 0) + 1
    assert set(counts.items()) == _EXPECTED_SITES, (
        f"field-ACL preamble sites changed: {sorted(counts.items())}. If this is "
        f"intentional, update _EXPECTED_SITES -- and make sure every copy still "
        f"matches the others."
    )


if __name__ == "__main__":
    import sys

    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
