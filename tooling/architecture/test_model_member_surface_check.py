"""Self-test for model_member_surface_check.py.

Stdlib + pytest only, like the gate it covers: no Odoo import, no database.

Three things are worth pinning, and they are the three ways this gate could
report success while measuring nothing:

* the **collector** reads each of the syntaxes the framework spells a model
  reach in, and rejects the two near-misses that produced false pairs on the
  first run (``env._lang.startswith``, ``env["base"].env``);
* the **BaseModel subtraction** is derived from the tree rather than listed, so
  a method moving between mixins must not turn into addon contract;
* the **Protocol rule** fires on a member the declared Protocol omits — the
  live defect this gate was written to find.

Run with::

    pytest tooling/architecture/test_model_member_surface_check.py
"""

import ast
import sys
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import model_member_surface_check as gate


def _pairs(source: str) -> set[tuple[str, str]]:
    """The ``(model, member)`` pairs the collector finds in *source*."""
    collector = gate._MemberCollector(gate.base_model_members())
    tree = ast.parse(textwrap.dedent(source))
    collector.bind(tree)
    collector.visit(tree)
    return {(model, member) for model, member, _ in collector.hits}


class TestCollector(unittest.TestCase):
    def test_subscript_on_env_and_registry_and_pool(self):
        self.assertEqual(
            _pairs("""
                env["ir.model.data"]._load_xmlid(a)
                self.env["ir.rule"]._compute_domain(b)
                registry["ir.http"]._dispatch(c)
                self.pool["ir.qweb"]._pregenerate_assets_bundles()
            """),
            {
                ("ir.model.data", "_load_xmlid"),
                ("ir.rule", "_compute_domain"),
                ("ir.http", "_dispatch"),
                ("ir.qweb", "_pregenerate_assets_bundles"),
            },
        )

    def test_recordset_accessor_on_environment(self):
        """``env.user`` resolves to ``res.users`` without naming it."""
        self.assertEqual(_pairs("env.user._is_public()"), {("res.users", "_is_public")})

    def test_one_transparent_call_is_stepped_over(self):
        """``sudo()`` and friends return the same model, so the member is its."""
        self.assertEqual(
            _pairs('env["ir.default"].sudo()._get_model_defaults(m)'),
            {("ir.default", "_get_model_defaults")},
        )

    def test_value_accessors_are_not_recordsets(self):
        """``env._lang`` is a ``str``.

        The reason :data:`gate.RECORDSET_ACCESSORS` is a strict subset of
        ``env_model_surface_check.ENV_MODEL_ACCESSORS`` rather than the same
        map: ``orm/fields/textual.py`` writes ``env._lang.startswith("_")``,
        which the wider map records as ``res.lang.startswith``.
        """
        self.assertEqual(_pairs('env._lang.startswith("_")'), set())
        self.assertEqual(_pairs("env.lang.upper()"), set())

    def test_basemodel_members_are_not_addon_contract(self):
        """``browse``/``search``/``sudo``/``env`` are the recordset protocol.

        Calling them on an addon-owned model asks ``base`` for nothing it did
        not inherit. ``env["base"].env.tz`` in ``tools/date_utils.py`` is the
        case that made the ``env`` entry load-bearing.
        """
        self.assertEqual(
            _pairs("""
                env["res.users"].browse(uid)
                env["ir.module.module"].search([])
                env["ir.attachment"].sudo()
                env["base"].env.tz
                env["res.users"]._fields
            """),
            set(),
        )

    def test_a_genuine_addon_member_survives_the_subtraction(self):
        self.assertEqual(
            _pairs('env["res.users"]._check_uid_passwd(a, b)'),
            {("res.users", "_check_uid_passwd")},
        )

    def test_a_single_assignment_local_is_followed(self):
        """``Access = env["ir.model.access"]`` ... ``Access.check(...)``.

        The channel the first version of this gate was blind to.
        ``ir.model.access`` is reached *only* this way, in
        ``orm/models/mixins/access.py``, so without it the model was absent from
        the surface entirely while sitting in ``env_model_surface_check``'s
        model set — a discrepancy with no explanation.
        """
        self.assertEqual(
            _pairs("""
                Access = env["ir.model.access"]
                Access.check(model, operation)
                Access._make_access_error(a, b)
            """),
            {("ir.model.access", "check"), ("ir.model.access", "_make_access_error")},
        )

    def test_a_twice_assigned_local_is_not_followed(self):
        """Soundness condition: one binding site, or the name is dropped.

        Two assignments mean the name could be either thing at the use site,
        and this gate does no dataflow. It must under-report rather than guess.
        """
        self.assertEqual(
            _pairs("""
                Thing = env["ir.model.access"]
                Thing = something_else()
                Thing.check(a)
            """),
            set(),
        )

    def test_a_local_bound_to_a_non_model_is_not_followed(self):
        self.assertEqual(_pairs("x = compute()\nx._invented()"), set())

    def test_a_non_model_string_is_not_a_model(self):
        self.assertEqual(_pairs('env["not a model"].anything()'), set())
        self.assertEqual(_pairs('config["db_maxconn"].anything()'), set())


class TestBaseModelMembers(unittest.TestCase):
    def test_it_is_measured_from_the_tree(self):
        members = gate.base_model_members()
        # A spread across the composition: if the scan silently found one file
        # or none, at least one of these is missing.
        for name in ("browse", "search", "sudo", "create", "write", "unlink"):
            self.assertIn(name, members, f"{name} is a BaseModel member")
        self.assertGreater(
            len(members), 200, "the BaseModel composition declares 250+ members"
        )

    def test_it_refuses_a_tree_it_cannot_read(self):
        original = gate._BASE_MODEL_TREE
        gate._BASE_MODEL_TREE = "odoo/orm/models_that_do_not_exist"
        try:
            with self.assertRaises(SystemExit):
                gate.base_model_members()
        finally:
            gate._BASE_MODEL_TREE = original


class TestProtocolRule(unittest.TestCase):
    def test_declared_members_are_read_from_source(self):
        module_rel, class_name = gate.PROTOCOLS["ir.http"]
        declared = gate.declared_members(module_rel, class_name)
        self.assertIn("_dispatch", declared)
        self.assertIn(
            "_apply_max_upload_size",
            declared,
            "the member http/_serve.py calls on every dispatched request",
        )

    def test_a_missing_protocol_class_refuses(self):
        with self.assertRaises(SystemExit):
            gate.declared_members("odoo/http/_protocols.py", "NoSuchProtocol")

    def test_a_missing_protocol_module_refuses(self):
        with self.assertRaises(SystemExit):
            gate.declared_members("odoo/http/_no_such_module.py", "HttpExtension")


class TestTheTreeItGuards(unittest.TestCase):
    def test_the_surface_matches_the_committed_baseline(self):
        report = gate.check()
        self.assertFalse(
            report.added,
            f"new (model, member) pairs not in KNOWN_MEMBER_SURFACE: "
            f"{sorted(report.added)}",
        )
        self.assertFalse(
            report.removed,
            f"pairs in KNOWN_MEMBER_SURFACE no longer reached (commit the "
            f"removal with --print-baseline): {sorted(report.removed)}",
        )

    def test_every_reached_member_is_declared_by_its_protocol(self):
        report = gate.check()
        self.assertFalse(
            report.undeclared,
            f"reached by core but absent from the model's Protocol: "
            f"{sorted(report.undeclared)}",
        )

    def test_the_docstrings_measured_block_is_fresh(self):
        import doc_measured

        problems = doc_measured.check(
            Path(gate.__file__), gate.doc_metrics(gate.check())
        )
        self.assertFalse(
            problems,
            "run: python tooling/architecture/model_member_surface_check.py "
            f"--update-doc\n{problems}",
        )


if __name__ == "__main__":
    unittest.main()
