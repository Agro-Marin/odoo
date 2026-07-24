"""DB-free tests for the lazy-builder routing rule (:class:`FasterRule`).

``FasterRule`` defers werkzeug's URL-builder compilation until the first
``url_for`` (:class:`LazyCompiledBuilder`), because most rules are only ever
matched (inbound dispatch), never built. These pin that (a) matching works
without ever compiling the builder, and (b) building still works when finally
needed. Run via ``pytest odoo/http/tests``.
"""

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
    """True when neither of werkzeug's two builders (append_unknown True/False)
    has materialised its real callable — i.e. the rule was never url_for-built."""
    builders = [getattr(rule, attr, None) for attr in ("_build", "_build_unknown")]
    return all(
        isinstance(b, LazyCompiledBuilder) and b._callable is None for b in builders
    )


def test_match_does_not_compile_the_builder():
    rule = FasterRule("/shop/<int:pid>", endpoint="shop")
    m = _map(rule)
    adapter = m.bind("example.com")
    # The whole point of FasterRule: a pure match must not force builder
    # compilation. Both werkzeug builders stay lazy through a match.
    endpoint, args = adapter.match("/shop/42")
    assert endpoint == "shop"
    assert args == {"pid": 42}
    assert _uncompiled(rule)  # never built


def test_build_materialises_lazily_and_works():
    rule = FasterRule("/shop/<int:pid>", endpoint="shop")
    m = _map(rule)
    adapter = m.bind("example.com")
    assert _uncompiled(rule)  # lazy until the first url_for
    built = adapter.build("shop", {"pid": 7})
    assert built == "/shop/7"
    # The first url_for materialises the builder werkzeug used (the
    # append_unknown=True one, ``_build_unknown``).
    assert rule._build_unknown._callable is not None


def test_faster_rule_is_a_drop_in_werkzeug_rule():
    # Same matching semantics as a plain Rule for a non-trivial converter set.
    fast = _map(FasterRule("/a/<int:n>", endpoint="e")).bind("h")
    plain = _map(werkzeug.routing.Rule("/a/<int:n>", endpoint="e")).bind("h")
    assert fast.match("/a/5") == plain.match("/a/5")


def test_concurrent_first_build_is_thread_safe():
    """Concurrent first builds of a shared rule all succeed and agree."""
    # Routing maps are shared across worker threads, so a rule's FIRST url_for
    # can race. The lazy builder used to delete its source attributes after
    # materialising; a peer that had already passed the None check then crashed
    # on self.rule (AttributeError → 500).
    n_threads = 8
    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # force preemption inside the tiny race window
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
                except Exception as exc:  # the failure mode under test
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
    # A converter-free static rule builds without args.
    rule = FasterRule("/health", endpoint="health")
    adapter = _map(rule).bind("h")
    assert adapter.match("/health") == ("health", {})
    assert adapter.build("health", {}) == "/health"
