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

import re
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

    #: Every module that resolves a checkout root, and the attribute holding it.
    #: Derived coverage is asserted by
    #: :meth:`test_the_agreement_list_covers_every_root_resolving_module`, because
    #: a hand-written list of eleven was the reason three tools kept counting
    #: parents unnoticed.
    ROOT_ATTRS = {
        ("architecture", "layer_check"): "ROOT",
        ("architecture", "js_layer_check"): "ROOT",
        ("architecture", "js_cycle_check"): "ROOT",
        ("architecture", "py_cycle_check"): "REPO_ROOT",
        ("architecture", "named_export_coherence"): "ROOT",
        ("architecture", "cross_repo_coherence"): "ROOT",
        ("architecture", "env_surface_check"): "REPO_ROOT",
        ("architecture", "env_model_surface_check"): "REPO_ROOT",
        ("architecture", "pool_surface_check"): "REPO_ROOT",
        ("architecture", "worker_thread_surface_check"): "REPO_ROOT",
        ("architecture", "mixin_coupling_check"): "ROOT",
        ("architecture", "libs_facade_check"): "REPO_ROOT",
        ("architecture", "package_index_check"): "REPO_ROOT",
        ("architecture", "subsystem_map_check"): "REPO_ROOT",
        ("architecture", "js_face_boundary"): "ROOT",
        ("architecture", "js_function_length"): "ROOT",
        ("architecture", "js_layer_cohesion"): "ROOT",
        ("architecture", "js_patch_blind_facade"): "ROOT",
        ("architecture", "js_private_access"): "ROOT",
        ("architecture", "js_public_surface"): "ROOT",
        ("architecture", "js_registry_layering"): "ROOT",
        ("architecture", "js_service_shape"): "ROOT",
        ("architecture", "js_suite_parity"): "ROOT",
        ("architecture", "naming_vocabulary"): "ROOT",
        ("architecture", "xml_reference_coherence"): "ROOT",
        ("typecheck", "scope_gate"): "ROOT",
        ("hoot", "hoot_lib"): "ODOO_ROOT",
        ("vendored", "check_vendored_libs"): "ODOO_ROOT",
        ("codegen", "generate_model_types"): "ODOO_ROOT",
        ("codegen", "generate_service_types"): "ODOO_ROOT",
        ("doclinks", "doc_link_gate"): "REPO_ROOT",
        ("domain_parity", "check_parity"): "REPO_ROOT",
    }

    def _roots(self):
        import importlib
        import sys

        for sub in sorted({sub for sub, _ in self.ROOT_ATTRS}):
            sys.path.insert(0, str(ODOO_ROOT / "tooling" / sub))
        roots = {}
        for (_sub, name), attr in self.ROOT_ATTRS.items():
            roots[name] = getattr(importlib.import_module(name), attr)
        return roots

    def test_all_tools_resolve_the_same_checkout_root(self):
        roots = self._roots()
        disagreeing = {name: r for name, r in roots.items() if Path(r) != ODOO_ROOT}
        assert not disagreeing, f"tools disagree about the checkout root: {disagreeing}"

    def test_the_agreement_list_covers_every_root_resolving_module(self):
        """The list above must not be narrower than the thing it guards.

        It named eleven modules while twenty-one resolve a root, and the ten it
        omitted included all three that were still counting parents. A coverage
        list that is itself unchecked reproduces the bug it exists to catch.
        """
        listed = {name for _sub, name in self.ROOT_ATTRS}
        resolving = set()
        for path in sorted((ODOO_ROOT / "tooling").rglob("*.py")):
            if "__pycache__" in path.parts or path.name.startswith("test_"):
                continue
            if path.name in ("_repo_root.py", "conftest.py"):
                continue
            text = path.read_text(encoding="utf-8")
            if "find_odoo_root(" in text and "def find_odoo_root" not in text:
                resolving.add(path.stem)
        missing = sorted(resolving - listed)
        assert not missing, (
            f"module(s) resolve a checkout root but are absent from ROOT_ATTRS, "
            f"so nothing asserts they agree: {missing}"
        )

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

    def test_no_tool_counts_parents_to_reach_the_checkout_root(self):
        """The OTHER half of the problem, which the grep above cannot see.

        The module docstring names both shapes — "a private copy of the marker
        walk or a ``parent.parent.parent``" — but only the first was pinned, so
        ``package_index_check``, ``subsystem_map_check`` and ``check_parity``
        counted parents for as long as they existed. They resolved correctly
        *today*, which is precisely why nobody noticed.

        A counted depth is fine for reaching something NEAR the file (``parent /
        "baselines"``); what must not be counted is the checkout root. The
        heuristic is depth: three or more levels up from ``tooling/<tool>/x.py``
        lands at or above the root.
        """
        counted = re.compile(
            r"""Path\(__file__\)\.resolve\(\)
                (?:\.parent){3,}          # .parent.parent.parent
              | Path\(__file__\)\.resolve\(\)\.parents\[\s*([2-9])\s*\]
            """,
            re.VERBOSE,
        )
        offenders = []
        for path in sorted((ODOO_ROOT / "tooling").rglob("*.py")):
            if "__pycache__" in path.parts or path.name == "test_repo_root.py":
                continue
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if counted.search(line.replace("pathlib.", "")):
                    offenders.append(f"{path.relative_to(ODOO_ROOT)}:{lineno}")
        assert not offenders, (
            f"checkout root reached by counting parents in: {offenders} — use "
            f"_repo_root.find_odoo_root(), which is depth-independent and "
            f"raises instead of guessing"
        )


class TestShellBootstrapsAgree:
    """The same agreement, for the two bootstraps that cannot import Python.

    ``tooling/_trampoline.sh`` and ``tooling/codegen/_resolve_env.sh`` re-derive
    the checkout root and the workspace in shell, because they run *before* an
    interpreter is chosen. Nothing tied them to ``_repo_root``, and they drifted
    exactly as the Python copies did: ``_resolve_env.sh`` kept the retired
    ``<ws>/addons/odoo`` shape-match long after the workspace was flattened to
    ``<ws>/odoo``, so it declared a repo-alone checkout — and
    ``regen_model_types.sh`` died with "no workspace to discover a config from"
    — in a workspace holding both a venv and a config. ``_trampoline.sh`` had
    been fixed; this one had not, which is the drift ``_trampoline.sh``'s own
    header says it was extracted to prevent.

    Pinned by BEHAVIOUR (what each script resolves) rather than by text, so a
    rewrite that keeps the answer right is free and one that does not is caught.
    """

    SHELL_BOOTSTRAPS = ("_trampoline.sh", "codegen/_resolve_env.sh")

    def test_both_shell_bootstraps_exist(self):
        for rel in self.SHELL_BOOTSTRAPS:
            assert (ODOO_ROOT / "tooling" / rel).is_file(), rel

    def test_resolve_env_agrees_with_find_workspace(self):
        """``_resolve_env.sh``'s WORKSPACE must equal ``find_workspace()``."""
        import subprocess

        script = ODOO_ROOT / "tooling" / "codegen" / "_resolve_env.sh"
        done = subprocess.run(
            ["bash", "-c", f'source "{script}"; printf "%s" "$WORKSPACE"'],
            capture_output=True,
            text=True,
            check=True,
        )
        expected = find_workspace(ODOO_ROOT)
        assert done.stdout == (str(expected) if expected else ""), (
            f"_resolve_env.sh resolved WORKSPACE={done.stdout!r} but "
            f"_repo_root.find_workspace() says {expected!r} — the shell copy "
            f"has drifted from the shared rule again"
        )

    def test_no_shell_bootstrap_hardcodes_only_the_addons_layout(self):
        """Both shapes must be handled, not just the historical one.

        A bootstrap that tests ``basename(dirname(root)) == "addons"`` and has
        no ``else`` branch reaching the parent is matching the retired layout
        only. That single line is the whole of the bug this class exists for.
        """
        offenders = []
        for rel in self.SHELL_BOOTSTRAPS:
            text = (ODOO_ROOT / "tooling" / rel).read_text(encoding="utf-8")
            if '= "addons"' not in text and '== "addons"' not in text:
                continue  # shape-match gone entirely: fine
            # The flat layout must be reachable too: something has to climb
            # exactly one level when the parent is not `addons`.
            if '/.."' not in text.replace('/../.."', ""):
                offenders.append(rel)
        assert not offenders, (
            f"shell bootstrap handles only <ws>/addons/odoo: {offenders} — the "
            f"workspace is flat (<ws>/odoo) now; see _repo_root.in_workspace"
        )
