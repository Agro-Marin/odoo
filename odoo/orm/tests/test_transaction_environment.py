import inspect
import logging
from unittest.mock import MagicMock, patch

import pytest

from odoo import fields, models
from odoo.orm.components.unit_of_work import UnitOfWork
from odoo.orm.model_test_env import model_test_env
from odoo.orm.runtime.environment import Environment
from odoo.orm.runtime.transaction import Transaction

_MOD = "test_orm_transaction_environment"


class Gadget(models.Model):
    _name = "txn.gadget"
    _module = _MOD
    _description = "Gadget"

    name = fields.Char()


class _FreshTransaction:
    def __init__(self, env):
        self._cr = env.cr
        self._root = env.transaction
        self.tx = Transaction(self._root.registry)

    def __enter__(self):
        self._cr.transaction = self.tx
        return self.tx

    def __exit__(self, *exc):
        self._cr.transaction = self._root
        return False


def test_the_constructor_and_the_transaction_intern_the_same_object():
    with model_test_env(Gadget) as env:
        cr, tx = env.cr, env.transaction
        built = Environment(cr, 7, {"lang": "fr_FR"})
        assert tx.environment(cr, 7, {"lang": "fr_FR"}) is built
        assert Environment(cr, 7, {"lang": "fr_FR"}, False) is built
        assert built in tx.envs


def test_the_last_environment_is_the_fast_path():
    with model_test_env(Gadget) as env:
        cr, tx = env.cr, env.transaction
        first = tx.environment(cr, 7, {"k": 1})
        assert tx._last_env() is first
        with patch.object(tx.envs, "get_environment", side_effect=AssertionError):
            assert tx.environment(cr, 7, {"k": 1}) is first
        other = tx.environment(cr, 7, {"k": 2})
        assert other is not first
        assert tx._last_env() is other


def test_superuser_is_normalised_to_su_by_the_transaction():
    with model_test_env(Gadget) as env:
        cr, tx = env.cr, env.transaction
        assert tx.environment(cr, 1, {}).su is True
        assert tx.environment(cr, 1, {}) is Environment(cr, 1, {}, su=True)


def test_the_first_real_user_is_adopted_only_when_no_opener_set_one():
    with model_test_env(Gadget) as env, _FreshTransaction(env) as tx:
        cr = env.cr
        assert tx.default_env is None
        tx.environment(cr, None, {})
        tx.environment(cr, 0, {})
        assert tx.default_env is None, "uid None and 0 are not real users"
        adopted = tx.environment(cr, 7, {})
        assert tx.default_env is adopted
        tx.environment(cr, 8, {})
        assert tx.default_env is adopted, "adoption happens once"


def test_an_explicit_default_env_is_never_overridden_by_construction():
    with model_test_env(Gadget) as env, _FreshTransaction(env) as tx:
        cr = env.cr
        opener = tx.environment(cr, None, {})
        tx.default_env = opener
        tx.environment(cr, 7, {})
        assert tx.default_env is opener


def test_flush_all_delegates_to_the_transaction_with_its_own_env():
    with model_test_env(Gadget) as env:
        user_env = Environment(env.cr, 7, {})
        with patch.object(Transaction, "flush") as flush:
            user_env.flush_all()
        flush.assert_called_once_with(user_env)


def test_flush_through_an_env_binds_that_env_and_skips_the_profiler_report():
    with model_test_env(Gadget) as env:
        tx = env.transaction
        user_env = Environment(env.cr, 7, {"probe": True})
        seen = []
        with patch.object(
            UnitOfWork,
            "flush_until_converged",
            side_effect=lambda recompute_fn, flush_fn: (
                seen.append((recompute_fn.__closure__, flush_fn.__closure__))
                or MagicMock(converged=True, iterations=0)
            ),
        ):
            tx._n1_tracker = MagicMock()
            tx.flush(user_env)
        assert seen, "the unit of work was not driven"
        bound = {c.cell_contents for cells in seen[0] for c in cells}
        assert user_env in bound, "the callbacks are not bound to the env given"
        tx._n1_tracker.report.assert_not_called()


def test_the_cursor_form_flushes_through_default_env_and_reports():
    with model_test_env(Gadget) as env:
        tx = env.transaction
        tx._n1_tracker = MagicMock()
        with patch.object(Transaction, "_flush_as") as flush_as:
            tx.flush()
        flush_as.assert_called_once_with(tx.default_env)
        tx._n1_tracker.report.assert_called_once_with()
        tx._n1_tracker.clear.assert_called_once_with()


def test_non_convergence_is_the_transactions_error(caplog):
    with model_test_env(Gadget) as env:
        tx = env.transaction
        stalled = MagicMock(converged=False, iterations=3, stalled_fields=["a.b"])
        with (
            patch.object(UnitOfWork, "flush_until_converged", return_value=stalled),
            pytest.raises(RuntimeError, match="did not converge"),
        ):
            tx.flush(env)
        tolerant = Environment(env.cr, env.uid, {"tolerant_recompute": True})
        with (
            patch.object(UnitOfWork, "flush_until_converged", return_value=stalled),
            caplog.at_level(logging.ERROR, logger="odoo.api"),
        ):
            tx.flush(tolerant)
        assert any("tolerant mode" in r.message for r in caplog.records)


def test_a_savepoint_rollback_leaves_default_env_to_its_writer():
    from odoo.db.savepoint import _FlushingSavepoint
    from odoo.orm.runtime.savepoint import _OrmFlushingSavepoint

    assert _OrmFlushingSavepoint._save_orm_state is _FlushingSavepoint._save_orm_state
    assert _OrmFlushingSavepoint.__slots__ == ()
    assert "default_env" not in inspect.getsource(_OrmFlushingSavepoint), (
        "the savepoint snapshots default_env again; whoever changes it inside a "
        "savepoint restores it, as http_routing._borrowed_public_env does"
    )


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
