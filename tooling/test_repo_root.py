"""Tests for the shared checkout-root anchor, and for every tool agreeing on it.

``_repo_root`` exists because each gate used to count directories up from
``__file__``. That is wrong twice over: the count breaks silently when a script
moves, and it cannot express that this repo is checked out in two shapes —
``<workspace>/addons/odoo`` locally, and ALONE as the CI checkout root.

The module was written but only three of the eleven tools used it; the rest kept
a private copy of the marker walk or a ``parent.parent.parent``. They all
resolved to the same directory *today*, which is precisely why the divergence
was invisible. This suite pins the agreement so it stays true.
"""

from pathlib import Path

import pytest
from _repo_root import (
    ODOO_MARKER,
    find_odoo_root,
    find_workspace,
    in_workspace,
    sibling_repos_root,
)

HERE = Path(__file__).resolve()
ODOO_ROOT = find_odoo_root(HERE, tool="test_repo_root")


class TestMarkerWalk:
    def test_resolves_to_the_directory_holding_the_marker(self):
        assert (ODOO_ROOT / ODOO_MARKER).is_file()

    def test_raises_instead_of_guessing_when_the_marker_is_absent(self):
        with pytest.raises(SystemExit) as excinfo:
            find_odoo_root(Path("/nonexistent/deep/path"), tool="probe")
        assert ODOO_MARKER in str(excinfo.value)
        assert "probe" in str(excinfo.value)

    def test_is_depth_independent(self):
        # The whole point: the answer must not depend on how deep the caller is.
        deep = ODOO_ROOT / "tooling" / "architecture" / "layer_check.py"
        assert find_odoo_root(deep) == ODOO_ROOT
        assert find_odoo_root(ODOO_ROOT / "tooling" / "conftest.py") == ODOO_ROOT


class TestCheckoutShape:
    def test_workspace_and_in_workspace_agree(self):
        assert (find_workspace(ODOO_ROOT) is not None) == in_workspace(ODOO_ROOT)

    def test_workspace_depth_matches_the_layout(self):
        """Two levels up when nested as ``<ws>/addons/odoo``, one when flat.

        This asserted ``parents[1]`` unconditionally, which pinned the nested
        layout as the only one. Flattening the workspace to ``<ws>/odoo`` then
        made every tool resolve the workspace to ``None`` and behave as though
        it were a repo-alone CI checkout.
        """
        workspace = find_workspace(ODOO_ROOT)
        if not in_workspace(ODOO_ROOT):
            assert workspace is None
        elif ODOO_ROOT.parent.name == "addons":
            assert workspace == ODOO_ROOT.parents[1]
        else:
            assert workspace == ODOO_ROOT.parent

    def test_sibling_repos_root_is_the_checkouts_parent(self):
        # The two used to share the name WORKSPACE across modules while naming
        # different directories, which is how the consumer repos ended up
        # configured at paths that never existed. They are still distinct
        # *concepts*; they merely coincide in the flat layout, where the sibling
        # checkouts sit directly under the workspace root.
        siblings = sibling_repos_root(ODOO_ROOT)
        assert siblings == ODOO_ROOT.parent
        workspace = find_workspace(ODOO_ROOT)
        if in_workspace(ODOO_ROOT) and ODOO_ROOT.parent.name == "addons":
            assert siblings != workspace
            assert siblings.parent == workspace

    def test_workspace_detection_survives_both_layouts(self, tmp_path):
        """Synthetic trees, so this holds wherever the suite itself runs."""
        # flat: <ws>/odoo, with the venv and conf at <ws>
        flat_ws = tmp_path / "flat"
        (flat_ws / "odoo").mkdir(parents=True)
        (flat_ws / "odoo" / "odoo-bin").touch()
        (flat_ws / "p314.conf").touch()
        assert in_workspace(flat_ws / "odoo")
        assert find_workspace(flat_ws / "odoo") == flat_ws

        # nested: <ws>/addons/odoo
        nested_ws = tmp_path / "nested"
        (nested_ws / "addons" / "odoo").mkdir(parents=True)
        (nested_ws / "addons" / "odoo" / "odoo-bin").touch()
        assert in_workspace(nested_ws / "addons" / "odoo")
        assert find_workspace(nested_ws / "addons" / "odoo") == nested_ws

        # repo-alone (CI): nothing above supplies a venv or a conf
        alone = tmp_path / "work" / "odoo"
        alone.mkdir(parents=True)
        (alone / "odoo-bin").touch()
        assert not in_workspace(alone)
        assert find_workspace(alone) is None


class TestEveryToolAgrees:
    """No tool may reintroduce a private root or a counted depth."""

    def _roots(self):
        import sys

        for sub in ("architecture", "typecheck", "hoot", "vendored", "codegen", "doclinks"):
            sys.path.insert(0, str(ODOO_ROOT / "tooling" / sub))
        import check_vendored_libs
        import cross_repo_coherence
        import doc_link_gate
        import generate_model_types
        import generate_service_types
        import hoot_lib
        import js_cycle_check
        import js_layer_check
        import layer_check
        import named_export_coherence
        import scope_gate

        return {
            "layer_check": layer_check.ROOT,
            "js_layer_check": js_layer_check.ROOT,
            "js_cycle_check": js_cycle_check.ROOT,
            "named_export_coherence": named_export_coherence.ROOT,
            "cross_repo_coherence": cross_repo_coherence.ROOT,
            "scope_gate": scope_gate.ROOT,
            "hoot_lib": hoot_lib.ODOO_ROOT,
            "check_vendored_libs": check_vendored_libs.ODOO_ROOT,
            "doc_link_gate": doc_link_gate.REPO_ROOT,
            "generate_service_types": generate_service_types.ODOO_ROOT,
            "generate_model_types": generate_model_types.ODOO_ROOT,
        }

    def test_all_tools_resolve_the_same_checkout_root(self):
        roots = self._roots()
        disagreeing = {name: r for name, r in roots.items() if Path(r) != ODOO_ROOT}
        assert not disagreeing, f"tools disagree about the checkout root: {disagreeing}"

    def test_no_tool_keeps_a_private_marker_walk(self):
        # A private copy is how two of them drifted out of reach of any fix to
        # the shared one.
        offenders = []
        for path in (ODOO_ROOT / "tooling").rglob("*.py"):
            if path.name in ("_repo_root.py", "test_repo_root.py"):
                continue
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            if "def _find_odoo_root" in text:
                offenders.append(str(path.relative_to(ODOO_ROOT)))
        assert not offenders, f"private marker walk reintroduced in: {offenders}"
