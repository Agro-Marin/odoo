import ast
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


def _parent_hops(node, known: dict) -> int | None:
    """How many `.parent` steps `node` is from the file that contains it.

    `Path(__file__).resolve()` is zero. `.parent` adds one and `.parents[n]`
    adds n + 1, because `p.parents[0]` *is* `p.parent`. A bare name resolves
    through `known`, which is what lets an intermediate variable be followed.
    Anything else is not a parent walk and answers None.
    """
    if isinstance(node, ast.Name):
        return known.get(node.id)
    if isinstance(node, ast.Attribute):
        if node.attr == "parent":
            inner = _parent_hops(node.value, known)
            return None if inner is None else inner + 1
        if node.attr == "resolve":
            return _parent_hops(node.value, known)
        return None
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "resolve":
            return _parent_hops(func.value, known)
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name == "Path" and len(node.args) == 1:
            arg = node.args[0]
            if isinstance(arg, ast.Name) and arg.id == "__file__":
                return 0
        return None
    if isinstance(node, ast.Subscript):
        value = node.value
        if not (isinstance(value, ast.Attribute) and value.attr == "parents"):
            return None
        index = node.slice
        if not (isinstance(index, ast.Constant) and isinstance(index.value, int)):
            return None
        inner = _parent_hops(value.value, known)
        return None if inner is None else inner + index.value + 1
    return None


def _lands_on(path: Path, target: Path) -> list[int]:
    """Line numbers in `path` whose parent walk lands exactly on `target`."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []

    known: dict[str, int] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        name = node.targets[0]
        hops = _parent_hops(node.value, known)
        if isinstance(name, ast.Name) and hops is not None:
            known[name.id] = hops

    hits = set()
    for node in ast.walk(tree):
        hops = _parent_hops(node, known)
        if hops and len(path.parents) >= hops and path.parents[hops - 1] == target:
            hits.add(node.lineno)
    return sorted(hits)


class TestMarkerWalk:
    def test_resolves_to_the_directory_holding_the_marker(self):
        assert (ODOO_ROOT / ODOO_MARKER).is_file()

    def test_raises_instead_of_guessing_when_the_marker_is_absent(self):
        with pytest.raises(SystemExit) as excinfo:
            find_odoo_root(Path("/nonexistent/deep/path"), tool="probe")
        assert ODOO_MARKER in str(excinfo.value)
        assert "probe" in str(excinfo.value)

    def test_is_depth_independent(self):
        deep = ODOO_ROOT / "tooling" / "architecture" / "layer_check.py"
        assert find_odoo_root(deep) == ODOO_ROOT
        assert find_odoo_root(ODOO_ROOT / "tooling" / "conftest.py") == ODOO_ROOT


class TestCheckoutShape:
    def test_workspace_and_in_workspace_agree(self):
        assert (find_workspace(ODOO_ROOT) is not None) == in_workspace(ODOO_ROOT)

    def test_workspace_depth_matches_the_layout(self):

        workspace = find_workspace(ODOO_ROOT)
        if not in_workspace(ODOO_ROOT):
            assert workspace is None
        elif ODOO_ROOT.parent.name == "addons":
            assert workspace == ODOO_ROOT.parents[1]
        else:
            assert workspace == ODOO_ROOT.parent

    def test_sibling_repos_root_is_the_checkouts_parent(self):
        siblings = sibling_repos_root(ODOO_ROOT)
        assert siblings == ODOO_ROOT.parent
        workspace = find_workspace(ODOO_ROOT)
        if in_workspace(ODOO_ROOT) and ODOO_ROOT.parent.name == "addons":
            assert siblings != workspace
            assert siblings.parent == workspace

    def test_workspace_detection_survives_both_layouts(self, tmp_path):
        flat_ws = tmp_path / "flat"
        (flat_ws / "odoo").mkdir(parents=True)
        (flat_ws / "odoo" / "odoo-bin").touch()
        (flat_ws / "p314.conf").touch()
        assert in_workspace(flat_ws / "odoo")
        assert find_workspace(flat_ws / "odoo") == flat_ws

        nested_ws = tmp_path / "nested"
        (nested_ws / "addons" / "odoo").mkdir(parents=True)
        (nested_ws / "addons" / "odoo" / "odoo-bin").touch()
        assert in_workspace(nested_ws / "addons" / "odoo")
        assert find_workspace(nested_ws / "addons" / "odoo") == nested_ws

        alone = tmp_path / "work" / "odoo"
        alone.mkdir(parents=True)
        (alone / "odoo-bin").touch()
        assert not in_workspace(alone)
        assert find_workspace(alone) is None


class TestEveryToolAgrees:
    ROOT_ATTRS = {
        ("architecture", "_consumer_scopes"): "ROOT",
        ("architecture", "doc_restated_counts"): "ROOT",
        ("architecture", "layer_check"): "ROOT",
        ("architecture", "js_layer_check"): "ROOT",
        ("architecture", "js_cycle_check"): "ROOT",
        ("architecture", "py_cycle_check"): "REPO_ROOT",
        ("architecture", "named_export_coherence"): "ROOT",
        ("architecture", "cross_repo_coherence"): "ROOT",
        ("architecture", "compute_context_deps"): "ROOT",
        ("architecture", "edi_vocabulary"): "ROOT",
        ("architecture", "env_surface_check"): "REPO_ROOT",
        ("architecture", "field_hook_naming"): "ROOT",
        ("architecture", "field_hook_purity"): "ROOT",
        ("architecture", "env_model_surface_check"): "REPO_ROOT",
        ("architecture", "model_member_surface_check"): "REPO_ROOT",
        ("architecture", "pool_surface_check"): "REPO_ROOT",
        ("architecture", "worker_thread_surface_check"): "REPO_ROOT",
        ("architecture", "mixin_coupling_check"): "ROOT",
        ("architecture", "module_depends_installable"): "ROOT",
        ("architecture", "libs_facade_check"): "REPO_ROOT",
        ("architecture", "facade_surface_check"): "REPO_ROOT",
        ("architecture", "mail_hook_keyword_check"): "ROOT",
        ("architecture", "package_index_check"): "REPO_ROOT",
        ("architecture", "subsystem_map_check"): "REPO_ROOT",
        ("architecture", "js_action_surface"): "ROOT",
        ("architecture", "js_duplication"): "ROOT",
        ("architecture", "js_face_boundary"): "ROOT",
        ("architecture", "js_function_length"): "ROOT",
        ("architecture", "py_function_length"): "ROOT",
        ("architecture", "py_x2many_count"): "ROOT",
        ("architecture", "sql_in_placeholder"): "ROOT",
        ("architecture", "py_count_as_boolean"): "ROOT",
        ("architecture", "py_shadowed_member"): "ROOT",
        ("architecture", "py_unresolved_calls"): "ROOT",
        ("architecture", "js_deployment_layers"): "ROOT",
        ("architecture", "js_arch_info_surface"): "ROOT",
        ("architecture", "js_env_config_surface"): "ROOT",
        ("architecture", "js_extension_surface"): "ROOT",
        ("architecture", "js_field_record_surface"): "ROOT",
        ("architecture", "js_layer_cohesion"): "ROOT",
        ("architecture", "js_mixin_coupling"): "ROOT",
        ("architecture", "js_patch_blind_facade"): "ROOT",
        ("architecture", "js_private_access"): "ROOT",
        ("architecture", "js_public_surface"): "ROOT",
        ("architecture", "js_registry_layering"): "ROOT",
        ("architecture", "js_service_shape"): "ROOT",
        ("architecture", "js_suite_parity"): "ROOT",
        ("architecture", "js_template_binding"): "ROOT",
        ("architecture", "js_vacuous_assertions"): "ROOT",
        ("architecture", "naming_vocabulary"): "ROOT",
        ("architecture", "order_line_qty"): "ROOT",
        ("architecture", "translation_catalog"): "ROOT",
        ("architecture", "sql_placeholder"): "ROOT",
        ("architecture", "xml_reference_coherence"): "ROOT",
        ("doclinks", "doc_symbol_gate"): "REPO_ROOT",
        ("typecheck", "scope_gate"): "ROOT",
        ("typecheck", "py_scope_gate"): "ROOT",
        ("typecheck", "tsconfig_paths"): "ROOT",
        ("hoot", "hoot_lib"): "ODOO_ROOT",
        ("vendored", "check_vendored_libs"): "ODOO_ROOT",
        ("codegen", "generate_model_types"): "ODOO_ROOT",
        ("codegen", "generate_service_types"): "ODOO_ROOT",
        ("doclinks", "doc_link_gate"): "REPO_ROOT",
        ("domain_parity", "check_parity"): "REPO_ROOT",
        ("trace", "stamp"): "ROOT",
        ("patchorder", "patchorder"): "ROOT",
        ("lint", "py_lint"): "REPO",
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
        """No tool may land on the checkout root by counting parents.

        The property is *where the expression lands*, not how many hops it took.
        A line-regex could only ask the second question, and got both ends of it
        wrong: it missed the spelling that goes through a variable --

            HERE = Path(__file__).resolve().parent
            REPO = HERE.parent.parent            # same sin, invisible to a regex

        -- while a fixed hop count cannot be right for every file anyway, since a
        module one level below `tooling/` reaches the root in two hops and one
        two levels below needs three. Resolving each binding against its own
        location answers the question that is actually being asked.
        """
        offenders = []
        for path in sorted((ODOO_ROOT / "tooling").rglob("*.py")):
            if "__pycache__" in path.parts or path.name == "test_repo_root.py":
                continue
            offenders.extend(
                f"{path.relative_to(ODOO_ROOT)}:{lineno}"
                for lineno in _lands_on(path, ODOO_ROOT)
            )
        assert not offenders, (
            f"checkout root reached by counting parents in: {offenders} — use "
            f"_repo_root.find_odoo_root(), which is depth-independent and "
            f"raises instead of guessing"
        )


class TestTheSweepSeesEverySpelling:
    """The sweep above is only worth its runtime if it cannot be evaded.

    Its predecessor could be, by assigning the walk to a name and continuing
    from there, so every spelling that reaches the checkout root is pinned here
    against a synthetic tree -- including the two that must NOT be flagged,
    because a sweep that fails those would push tools away from `.parent` for
    the directory they legitimately own.
    """

    @staticmethod
    def _probe(tmp_path, source):
        root = tmp_path / "checkout"
        directory = root / "tooling" / "lint"
        directory.mkdir(parents=True)
        (root / ODOO_MARKER).write_text("")
        probe = directory / "probe.py"
        probe.write_text(source)
        return _lands_on(probe, root)

    @pytest.mark.parametrize(
        "spelling",
        [
            "REPO = Path(__file__).resolve().parent.parent.parent",
            "REPO = Path(__file__).resolve().parents[2]",
            "HERE = Path(__file__).resolve().parent\nREPO = HERE.parent.parent",
            "A = Path(__file__).resolve().parent\nB = A.parent\nREPO = B.parent",
            "REPO = pathlib.Path(__file__).resolve().parent.parent.parent",
        ],
    )
    def test_every_way_of_reaching_the_root_is_caught(self, tmp_path, spelling):
        assert self._probe(tmp_path, spelling + "\n"), (
            f"the sweep did not see: {spelling!r}"
        )

    @pytest.mark.parametrize(
        "spelling",
        [
            "HERE = Path(__file__).resolve().parent",
            "TOOLING = Path(__file__).resolve().parents[1]",
            "SIBLING = Path(__file__).resolve().parent / 'data'",
        ],
    )
    def test_a_walk_that_stops_short_of_the_root_is_left_alone(
        self, tmp_path, spelling
    ):
        assert not self._probe(tmp_path, spelling + "\n"), (
            f"the sweep flagged a walk that does not reach the root: {spelling!r}"
        )


class TestShellBootstrapsAgree:
    SHELL_BOOTSTRAPS = ("_trampoline.sh", "codegen/_resolve_env.sh")

    def test_both_shell_bootstraps_exist(self):
        for rel in self.SHELL_BOOTSTRAPS:
            assert (ODOO_ROOT / "tooling" / rel).is_file(), rel

    def test_resolve_env_agrees_with_find_workspace(self):
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

        offenders = []
        for rel in self.SHELL_BOOTSTRAPS:
            text = (ODOO_ROOT / "tooling" / rel).read_text(encoding="utf-8")
            if '= "addons"' not in text and '== "addons"' not in text:
                continue
            if '/.."' not in text.replace('/../.."', ""):
                offenders.append(rel)
        assert not offenders, (
            f"shell bootstrap handles only <ws>/addons/odoo: {offenders} — the "
            f"workspace is flat (<ws>/odoo) now; see _repo_root.in_workspace"
        )
