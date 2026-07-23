"""Regression tests for ``check_indexes`` staleness detection.

Tier-2 suite: real ``import odoo``, stub cursor, no database.

The fork emits partial ``WHERE ... IS NOT NULL`` indexes for
``index='btree_not_null'`` (including the company-dependent variant), but both
plain btree and the partial variant use the ``btree`` access method — so
staleness detection must also compare **predicate presence**, not only the
access method, or a ``'btree'`` <-> ``'btree_not_null'`` change never rebuilds
the index. Also pins the ``ValueError`` on an invalid ``index=`` value
(converted from ``assert`` so it holds under ``python -O``).
"""

from contextlib import contextmanager

import pytest

from odoo.orm.runtime.registry import Registry
from odoo.tools import sql


class _Field:
    column_type = ("varchar", "varchar")
    store = True
    translate = False
    company_dependent = False
    manual = False

    def __init__(self, name, index, *, company_dependent=False):
        self.name = name
        self.index = index
        self.company_dependent = company_dependent

    def __repr__(self):
        return f"fake.model.{self.name}"


def _make_registry(*fields):
    class _Model:
        _table = "fake_model"
        _auto = True
        _abstract = False
        _fields = {f.name: f for f in fields}

    reg = object.__new__(Registry)
    reg.models = {"fake.model": _Model}
    reg.has_trigram = False
    reg.has_unaccent = False
    return reg


class _IdxCursor:
    """Stub cursor: canned introspection rows, records every executed query."""

    def __init__(self, existing_rows):
        self._rows = existing_rows
        self.executed = []
        # index_exists() checks rowcount after its SELECT; 0 = "no index",
        # which is correct right after the drop that precedes a recreate.
        self.rowcount = 0

    def execute(self, query, params=None, **kwargs):
        self.executed.append(getattr(query, "code", query))

    def fetchall(self):
        return self._rows

    @contextmanager
    def savepoint(self, flush=True):
        yield


_IDX = sql.make_index_name("fake_model", "state")


def test_btree_to_btree_not_null_marks_stale():
    """Existing plain btree + field now btree_not_null => drop and recreate."""
    reg = _make_registry(_Field("state", "btree_not_null"))
    cr = _IdxCursor([(_IDX, "fake_model", "btree", False)])

    reg.check_indexes(cr, ["fake.model"])

    executed = "\n".join(cr.executed)
    assert "DROP INDEX" in executed
    assert "CREATE INDEX" in executed
    assert "IS NOT NULL" in executed  # recreated as a partial index


def test_btree_not_null_to_btree_marks_stale():
    """Existing partial index + field now plain btree => recreate without WHERE."""
    reg = _make_registry(_Field("state", True))
    cr = _IdxCursor([(_IDX, "fake_model", "btree", True)])

    reg.check_indexes(cr, ["fake.model"])

    executed = "\n".join(cr.executed)
    assert "DROP INDEX" in executed
    creates = [q for q in cr.executed if "CREATE INDEX" in q]
    assert creates
    assert all("WHERE" not in q for q in creates)


def test_company_dependent_btree_not_null_expects_predicate():
    reg = _make_registry(
        _Field("state", "btree_not_null", company_dependent=True)
    )
    cr = _IdxCursor([(_IDX, "fake_model", "btree", False)])

    reg.check_indexes(cr, ["fake.model"])

    executed = "\n".join(cr.executed)
    assert "DROP INDEX" in executed
    assert "IS NOT NULL" in executed


def test_matching_partial_index_not_rebuilt():
    """btree_not_null field with an existing predicated btree index: no-op."""
    reg = _make_registry(_Field("state", "btree_not_null"))
    cr = _IdxCursor([(_IDX, "fake_model", "btree", True)])

    reg.check_indexes(cr, ["fake.model"])

    assert len(cr.executed) == 1  # the introspection query only


def test_matching_plain_index_not_rebuilt():
    reg = _make_registry(_Field("state", True))
    cr = _IdxCursor([(_IDX, "fake_model", "btree", False)])

    reg.check_indexes(cr, ["fake.model"])

    assert len(cr.executed) == 1


def test_access_method_mismatch_still_stale():
    """The pre-existing method check keeps working (gin left behind)."""
    reg = _make_registry(_Field("state", True))
    cr = _IdxCursor([(_IDX, "fake_model", "gin", False)])

    reg.check_indexes(cr, ["fake.model"])

    executed = "\n".join(cr.executed)
    assert "DROP INDEX" in executed
    assert "CREATE INDEX" in executed


def test_invalid_index_value_raises_value_error():
    """Module-author input is validated with ValueError (holds under -O)."""
    reg = _make_registry(_Field("state", "bogus"))
    cr = _IdxCursor([])

    with pytest.raises(ValueError, match="bogus"):
        reg.check_indexes(cr, ["fake.model"])
