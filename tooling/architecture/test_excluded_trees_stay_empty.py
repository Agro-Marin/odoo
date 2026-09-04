"""A tree a gate skips must hold nothing that gate would have reported.

`_sources.is_test_path` calls any path with a `tests` component a test path.
That is right for the real suites under `odoo/orm/tests` and its siblings,
and wrong for exactly one tree: `odoo/tests` is the test FRAMEWORK --
TransactionCase, HttpCase, Form, the Chrome CDP driver, the suite runner, the
result reporter -- production code every addon test in this repository runs on,
excluded by the name of its directory rather than by anything about it.

Four gates were onboarded to it directly, each with its own `tests` scope and
floor: sql_in_placeholder, py_count_as_boolean, py_x2many_count, py_hook_arity.
Two were not, and this file is why. `naming_vocabulary` reports only on model
classes and `compute_context_deps` only on field computes, and the framework
defines neither -- it is classes and methods in quantity and not one model
among them. A scope over it would scan every file and report on nothing, and a
scope resolving to nothing is the defect these gates exist to prevent, not a
way to close one. No count is restated here on purpose: the assertions below
are the measurement, and a figure in this docstring would be a second copy of
it that drifts.

The exclusion is therefore sound on a premise -- and a premise checked once is
an assumption. These tests are that premise, restated as a measurement, so the
day someone puts a model or a compute in the test framework the gate that
cannot see it says so instead of staying quietly green.

The predicates come from the gates themselves. Asserting against a local copy
would let this file and the gate drift apart, which is the failure it exists to
catch one level down.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _sources
import compute_context_deps as ccd
import naming_vocabulary as nv
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="excluded_trees_stay_empty")
FRAMEWORK = ROOT / "odoo" / "tests"

ONBOARD = (
    "Onboard the gate to this tree the way sql_in_placeholder, "
    "py_count_as_boolean, py_x2many_count and py_hook_arity were: a TESTS "
    "scope, a row in GOVERNED_ADDONS and its own floor. Do not simply delete "
    "this assertion -- it is the record of why the scope was judged "
    "unnecessary, and that judgement has just expired."
)


def framework_files() -> list[Path]:
    return sorted(p for p in FRAMEWORK.rglob("*.py") if "__pycache__" not in p.parts)


def test_the_framework_tree_is_actually_there():
    # The canary. Every assertion below passes vacuously over an empty list,
    # which is the shape of bug this whole file is about.
    files = framework_files()
    assert len(files) >= 15, (
        f"{_sources.display(FRAMEWORK, ROOT)} yielded {len(files)} Python files. "
        f"The tree has moved or been renamed, and the two assertions below are now "
        f"measuring nothing while still passing."
    )


def offenders(predicate, node_type) -> list[str]:
    # display(), not relative_to(): it falls back to the absolute path rather
    # than raising on anything outside ROOT.
    return [
        f"{_sources.display(path, ROOT)}:{node.lineno} {node.name}"
        for path in framework_files()
        for node in ast.walk(ast.parse(path.read_bytes()))
        if isinstance(node, node_type) and predicate(node)
    ]


def test_the_framework_defines_no_model_class():
    found = offenders(nv.is_model_class, ast.ClassDef)
    assert not found, (
        "naming_vocabulary reports on model classes and skips this tree, so "
        "these are ungoverned by the `naming` floor:\n  "
        + "\n  ".join(found)
        + f"\n{ONBOARD}"
    )


def test_the_framework_defines_no_field_compute():
    found = offenders(ccd.is_field_compute, ast.FunctionDef)
    assert not found, (
        "compute_context_deps reports on field computes and skips this tree, "
        "so these are ungoverned by the `computectx` floor:\n  "
        + "\n  ".join(found)
        + f"\n{ONBOARD}"
    )


def test_the_predicates_still_recognise_what_they_are_named_for():
    # Both assertions above are "found nothing". That is indistinguishable from
    # a predicate that has stopped matching anything at all, so each is shown a
    # positive case here.
    model = ast.parse(
        "class M(models.Model):\n    _name = 'x'\n    def f(self): pass\n"
    ).body[0]
    assert isinstance(model, ast.ClassDef)
    assert nv.is_model_class(model), (
        "naming_vocabulary.is_model_class no longer recognises a plain "
        "models.Model subclass; the model-class assertion above is vacuous"
    )

    compute = ast.parse(
        "@api.depends('a')\ndef _compute_thing(self):\n    self.x = self.env.context\n"
    ).body[0]
    assert isinstance(compute, ast.FunctionDef)
    assert ccd.is_field_compute(compute), (
        "compute_context_deps.is_field_compute no longer recognises a "
        "@api.depends compute; the compute assertion above is vacuous"
    )
