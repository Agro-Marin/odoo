"""``CONVENTIONAL_FIELD_NAMES`` is data, so it must be read by something.

The table in ``orm/primitives.py`` collects the field names the ORM attaches
behaviour to *purely because of the name* — the five that were previously five
inline string literals spread across four Layer-1 modules, with nothing telling
a reader that calling a field ``sequence`` changes its aggregator.

Collecting them was the right instinct, but as unread data the table drifts
exactly like the prose it replaced, with the added cost of looking
authoritative: its own docstring concedes "This mapping is documentation", and
the only two references to it in the tree are *comments*. These assertions make
it a claim.

Two of the five are backed by exported constants because the ORM *branches* on
them (``STATE_FIELD``, ``SEQUENCE_FIELD``). The other three are not, and
deliberately: ``currency_id``/``company_id``/``display_name`` appear in Layer 1
in contexts that are not the convention — ``value.mapped("display_name")`` is a
field read, not a name-triggered rule — so a constant would imply a uniformity
that does not exist. What is asserted for those is that the ORM still mentions
them at all.
"""

import re
from pathlib import Path

import pytest

from odoo.orm.primitives import (
    CONVENTIONAL_FIELD_NAMES,
    SEQUENCE_FIELD,
    STATE_FIELD,
)

_ORM = Path(__file__).resolve().parents[1]

#: The two the ORM branches on, and the constant each must be reached through.
BRANCHED = {"state": STATE_FIELD, "sequence": SEQUENCE_FIELD}


def _layer1_sources() -> list[Path]:
    return sorted(
        p
        for p in (_ORM / "fields").rglob("*.py")
        if "tests" not in p.parts and p.name != "__init__.py"
    )


class TestTheTableMatchesTheCode:
    def test_the_branched_names_are_exported_as_constants(self):
        for name, constant in BRANCHED.items():
            assert constant == name
            assert name in CONVENTIONAL_FIELD_NAMES

    @pytest.mark.parametrize("name", sorted(BRANCHED))
    def test_a_branched_name_is_never_compared_as_a_bare_literal(self, name):
        """The point of exporting the constant is that the branch uses it.

        A bare ``name == "state"`` in Layer 1 would work and would be invisible
        to anyone reading the table, which is the state this table was created
        to end.
        """
        pattern = re.compile(rf'(name|self\.name)\s*==\s*[\'"]{name}[\'"]')
        offenders = [
            f"{path.relative_to(_ORM)}:{lineno}"
            for path in _layer1_sources()
            for lineno, line in enumerate(path.read_text().splitlines(), 1)
            if pattern.search(line)
        ]
        assert not offenders, (
            f"{name!r} is compared as a literal at {offenders}; use the "
            f"exported constant so primitives.CONVENTIONAL_FIELD_NAMES stays "
            f"the single place the convention is written down"
        )

    @pytest.mark.parametrize("name", sorted(CONVENTIONAL_FIELD_NAMES))
    def test_every_documented_name_is_still_referenced_by_the_orm(self, name):
        """A convention the ORM stopped honouring must leave the table.

        This is the drift the table is exposed to: a name is dropped from the
        code and the documentation keeps asserting it.
        """
        needle = f'"{name}"'
        constant = BRANCHED.get(name)
        # primitives.py is excluded because it DEFINES the table: searching it
        # finds every key by construction, which made the first version of this
        # assertion vacuous -- adding a fabricated entry passed.
        found = any(
            needle in text or (constant is not None and f"{name.upper()}_FIELD" in text)
            for text in (
                path.read_text()
                for path in _ORM.rglob("*.py")
                if path.name != "primitives.py" and "tests" not in path.parts
            )
        )
        assert found, (
            f"{name!r} is documented in CONVENTIONAL_FIELD_NAMES but no longer "
            f"appears anywhere in odoo/orm -- either the behaviour moved, or "
            f"the entry is stale"
        )

    def test_each_entry_explains_what_the_name_triggers(self):
        for name, explanation in CONVENTIONAL_FIELD_NAMES.items():
            assert explanation.strip(), f"{name} has no explanation"
            assert len(explanation) > 20, (
                f"{name}'s entry is too short to say what the name does: "
                f"{explanation!r}"
            )
