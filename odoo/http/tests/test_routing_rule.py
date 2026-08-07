import sys
import threading

import werkzeug.routing

from odoo.http.routing import FasterRule, LazyCompiledBuilder


def _map(*rules):
    m = werkzeug.routing.Map(strict_slashes=False)
    for r in rules:
        m.add(r)
    return m


def _uncompiled(rule):
    builders = [getattr(rule, attr, None) for attr in ("_build", "_build_unknown")]
    return all(
        isinstance(b, LazyCompiledBuilder) and b._callable is None for b in builders
    )


def test_match_does_not_compile_the_builder():
    rule = FasterRule("/shop/<int:pid>", endpoint="shop")
    m = _map(rule)
    adapter = m.bind("example.com")
    endpoint, args = adapter.match("/shop/42")
    assert endpoint == "shop"
    assert args == {"pid": 42}
    assert _uncompiled(rule)


def test_build_materialises_lazily_and_works():
    rule = FasterRule("/shop/<int:pid>", endpoint="shop")
    m = _map(rule)
    adapter = m.bind("example.com")
    assert _uncompiled(rule)
    built = adapter.build("shop", {"pid": 7})
    assert built == "/shop/7"
    assert rule._build_unknown._callable is not None


def test_faster_rule_is_a_drop_in_werkzeug_rule():
    fast = _map(FasterRule("/a/<int:n>", endpoint="e")).bind("h")
    plain = _map(werkzeug.routing.Rule("/a/<int:n>", endpoint="e")).bind("h")
    assert fast.match("/a/5") == plain.match("/a/5")


def test_concurrent_first_build_is_thread_safe():
    n_threads = 8
    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        for _ in range(20):
            rule = FasterRule("/x/<int:i>/<name>", endpoint="e")
            adapter = _map(rule).bind("h")
            barrier = threading.Barrier(n_threads)
            results, errors = [], []

            def build(adapter=adapter, barrier=barrier, results=results, errors=errors):
                barrier.wait()
                try:
                    results.append(adapter.build("e", {"i": 1, "name": "a"}))
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=build) for _ in range(n_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            assert not errors
            assert results == ["/x/1/a"] * n_threads
    finally:
        sys.setswitchinterval(old_interval)


def test_empty_endpoint_map_build_roundtrip():
    rule = FasterRule("/health", endpoint="health")
    adapter = _map(rule).bind("h")
    assert adapter.match("/health") == ("health", {})
    assert adapter.build("health", {}) == "/health"
