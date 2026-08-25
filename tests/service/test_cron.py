"""Pure-pytest tests for ``odoo.service._cron`` and its database-list helper.

Both the prefork ``WorkerCron`` and the threaded ``_listen_thread`` feed
``order_notified_first``'s result straight into a per-database processing loop,
so a duplicate in its output runs a database twice in one pass — and both
resolve which databases to serve through ``_helpers.cron_database_list``.

Moved out of ``test_server.py``, whose subject is the HTTP/prefork/threaded
servers; the cron scheduling rule is shared by two of them and owned by
neither.

Run with::

    python -m pytest tests/service/test_cron.py -v
"""

from unittest.mock import patch

import pytest

from odoo.service import _helpers


class TestCronDatabaseList:
    """``cron_database_list()``: config override vs ``list_dbs`` fallback.

    ``config["db_name"]`` is a LIST at runtime under every invocation form —
    unset gives ``[]``, ``-d mydb`` gives ``["mydb"]``, ``-d a,b,c`` gives
    ``["a", "b", "c"]`` — and both callers do ``OrderedSet(cron_database_list())``.
    These tests used to feed a bare string and a ``None``, neither of which the
    config can produce, and the string one asserted the pass-through: with
    ``db_name = "mydb"`` the callers would have iterated it into four
    one-character "databases" and run the cron pass against each.  Pinning a
    shape production cannot produce also means a refactor that correctly
    normalised the type would fail here.
    """

    def test_returns_the_configured_databases(self):
        with (
            patch("odoo.service._helpers.config", {"db_name": ["db1", "db2"]}),
            patch("odoo.service._helpers.list_dbs") as mock_list,
        ):
            result = _helpers.cron_database_list()
        assert result == ["db1", "db2"]
        mock_list.assert_not_called()

    def test_a_single_configured_database_is_still_a_list(self):
        """``-d mydb`` is ``["mydb"]``, and the callers iterate the result."""
        with (
            patch("odoo.service._helpers.config", {"db_name": ["mydb"]}),
            patch("odoo.service._helpers.list_dbs"),
        ):
            result = _helpers.cron_database_list()
        assert list(result) == ["mydb"]

    def test_falls_back_to_list_dbs_when_empty(self):
        """Unset is ``[]``, not ``None``."""
        with (
            patch("odoo.service._helpers.config", {"db_name": []}),
            patch(
                "odoo.service._helpers.list_dbs", return_value=["db1", "db2"]
            ) as mock_list,
        ):
            result = _helpers.cron_database_list()
        mock_list.assert_called_once_with(True)
        assert result == ["db1", "db2"]

    def test_the_result_survives_the_ordered_set_the_callers_build(self):
        """Both drivers do ``OrderedSet(cron_database_list())``.  A string would
        pass every assertion above and still decompose into characters here."""
        from odoo.tools.misc import OrderedSet

        with (
            patch("odoo.service._helpers.config", {"db_name": ["mydb"]}),
            patch("odoo.service._helpers.list_dbs"),
        ):
            assert list(OrderedSet(_helpers.cron_database_list())) == ["mydb"]


# ---------------------------------------------------------------------------
# _cron.order_notified_first — scheduling order + de-duplication
# ---------------------------------------------------------------------------


class TestOrderNotifiedFirst:
    """``order_notified_first`` orders served databases with notified ones first
    and each database exactly once.

    The cron/job drivers feed its result straight into a per-database process
    loop, so a duplicate would run a database twice in one pass.  Today's callers
    pass de-duplicated ``OrderedSet``s, but the function must be correct by
    construction for any iterable — these tests pin that contract.
    """

    @pytest.fixture
    def order(self):
        from odoo.service._cron import order_notified_first

        return order_notified_first

    def test_notified_come_first_in_notified_order(self, order):
        assert order(["c", "a"], ["a", "b", "c"]) == ["c", "a", "b"]

    def test_stray_notified_for_unknown_db_is_dropped(self, order):
        assert order(["x"], ["a", "b"]) == ["a", "b"]

    def test_empty_notified_preserves_all_dbs_order(self, order):
        assert order([], ["a", "b", "c"]) == ["a", "b", "c"]

    def test_duplicate_notified_yields_db_once(self, order):
        # Regression: the prior implementation emitted ``notified`` verbatim, so
        # a db listed twice was processed twice in one cron pass.
        assert order(["a", "a"], ["a", "b"]) == ["a", "b"]
        assert order(["c", "c", "a"], ["a", "b", "c"]) == ["c", "a", "b"]

    def test_duplicate_in_all_dbs_yields_db_once(self, order):
        assert order([], ["a", "a", "b"]) == ["a", "b"]

    @pytest.mark.parametrize("seed", range(20))
    def test_output_is_a_dedup_permutation_of_served_dbs(self, order, seed):
        import random

        rng = random.Random(seed)
        all_dbs = [f"db{i}" for i in range(rng.randint(0, 8))]
        notified = [
            rng.choice(all_dbs)
            if all_dbs and rng.random() < 0.7
            else f"stray{rng.randint(0, 3)}"
            for _ in range(rng.randint(0, 6))
        ]
        result = order(notified, all_dbs)
        # exactly the served set, each once, no strays
        assert sorted(result) == sorted(set(all_dbs))
        assert len(result) == len(set(result))
        # every notified-and-served db precedes every non-notified served db
        notified_served = [d for d in dict.fromkeys(notified) if d in set(all_dbs)]
        assert result[: len(notified_served)] == notified_served
