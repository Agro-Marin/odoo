import threading
import unittest

from odoo.orm.domain import optimizations  # noqa: F401
from odoo.orm.domain.ast import (
    Domain,
    DomainNary,
    DomainNot,
    OptimizationLevel,
)

_ITERATIONS = 150
_FALSY_BY_TYPE = {"char": "", "integer": 0, "boolean": False}


class _Field:
    def __init__(self, name, ftype, model_name):
        self.name = name
        self.type = ftype
        self.relational = False
        self.model_name = model_name
        self.comodel_name = None
        self.store = True
        self.required = False
        self.inherited = False
        self.company_dependent = False
        self.falsy_value = _FALSY_BY_TYPE.get(ftype)


class _Model:
    def __init__(self, name, field_types):
        self._name = name
        self._fields = {n: _Field(n, t, name) for n, t in field_types.items()}


def _build_domain():
    return (Domain("a", "=", 5) & Domain("b", "in", [1, 2, 5])) | (
        Domain("a", "in", [5, 6]) & Domain("b", "!=", 0)
    )


def _iter_nodes(domain):
    stack = [domain]
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, DomainNary):
            stack.extend(node.children)
        elif isinstance(node, DomainNot):
            stack.append(node.child)


class TestOptStampConcurrency(unittest.TestCase):
    def setUp(self):
        self.m_seed = _Model("m_seed", {"a": "integer", "b": "integer"})
        self.m_int = _Model("m_int", {"a": "integer", "b": "integer"})
        self.m_bool = _Model("m_bool", {"a": "boolean", "b": "boolean"})
        self.expected_int = list(_build_domain().optimize(self.m_int))
        self.expected_bool = list(_build_domain().optimize(self.m_bool))
        self.assertNotEqual(self.expected_int, self.expected_bool)

    def test_cross_model_concurrent_optimize_copies_and_never_tears(self):
        errors = []
        known_stamped_models = {None, "m_seed"}

        for _ in range(_ITERATIONS):
            shared = _build_domain().optimize(self.m_seed)
            stamps_before = {id(node): node._opt for node in _iter_nodes(shared)}
            barrier = threading.Barrier(3)
            results = {}
            samples = []
            failures = []

            def optimize(
                model,
                key,
                barrier=barrier,
                shared=shared,
                results=results,
                failures=failures,
            ):
                try:
                    barrier.wait()
                    results[key] = shared.optimize(model)
                except Exception as exc:
                    failures.append(exc)

            def read_stamps(barrier=barrier, shared=shared, samples=samples):
                barrier.wait()
                for _ in range(30):
                    samples.extend(node._opt for node in _iter_nodes(shared))

            threads = [
                threading.Thread(target=optimize, args=(self.m_int, "int")),
                threading.Thread(target=optimize, args=(self.m_bool, "bool")),
                threading.Thread(target=read_stamps),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            if failures:
                errors.append(("exception", failures))
                continue

            if list(results["int"]) != self.expected_int:
                errors.append(("int-result", list(results["int"])))
            if list(results["bool"]) != self.expected_bool:
                errors.append(("bool-result", list(results["bool"])))

            errors.extend(
                ("shared-restamped", node._opt, stamps_before[id(node)])
                for node in _iter_nodes(shared)
                if node._opt != stamps_before[id(node)]
            )
            errors.extend(
                ("no-copy", key) for key in ("int", "bool") if results[key] is shared
            )

            errors.extend(
                ("torn-sample", stamp)
                for stamp in samples
                if not isinstance(stamp[0], OptimizationLevel)
                or stamp[1] not in known_stamped_models
            )

            for key, model_name in (("int", "m_int"), ("bool", "m_bool")):
                errors.extend(
                    ("result-stamp", key, node._opt)
                    for node in _iter_nodes(results[key])
                    if node._opt[1] not in (None, model_name)
                )

            self.assertIs(shared.optimize(self.m_seed), shared)

        self.assertEqual(errors, [])

    def test_same_model_interleaving_is_benign(self):
        errors = []

        for _ in range(_ITERATIONS):
            shared = _build_domain()
            barrier = threading.Barrier(2)
            results = {}
            failures = []

            def optimize(
                key, barrier=barrier, shared=shared, results=results, failures=failures
            ):
                try:
                    barrier.wait()
                    results[key] = shared.optimize(self.m_int)
                except Exception as exc:
                    failures.append(exc)

            threads = [
                threading.Thread(target=optimize, args=(key,))
                for key in ("first", "second")
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            if failures:
                errors.append(("exception", failures))
                continue
            for key in ("first", "second"):
                if list(results[key]) != self.expected_int:
                    errors.append((key, list(results[key])))
                errors.extend(
                    ("stamp", key, node._opt)
                    for node in _iter_nodes(results[key])
                    if node._opt[1] not in (None, "m_int")
                )

        self.assertEqual(errors, [])
