from types import SimpleNamespace

from odoo.orm.fields.reference import REFERENCE_VERIFIED_CACHE_KEY, Reference


def _env_with_memo(memo):
    return SimpleNamespace(
        cr=SimpleNamespace(cache={REFERENCE_VERIFIED_CACHE_KEY: memo})
    )


def test_discard_drops_only_the_named_models():
    memo = {
        ("m", "ref"): {("res.partner", 1), ("res.users", 2)},
        ("m2", "other_ref"): {("res.partner", 3)},
    }
    env = _env_with_memo(memo)
    Reference.discard_verified_models(env, ["res.partner"])
    assert memo[("m", "ref")] == {("res.users", 2)}
    assert memo[("m2", "other_ref")] == set()


def test_discard_without_a_memo_is_a_no_op():
    env = SimpleNamespace(cr=SimpleNamespace(cache={}))
    Reference.discard_verified_models(env, ["res.partner"])
    assert env.cr.cache == {}
