import ast
import functools
from collections import defaultdict
from pathlib import Path

from lxml import etree

from odoo.modules import Manifest

from . import lint_case

# where elevation is the kernel's or not production code at all
_SKIPPED_PARTS = frozenset({"tests", "migrations", "upgrades", "populate", "static"})
_GROUP_CHECKS = frozenset({"has_group", "has_groups", "_has_group"})
_MEMBERSHIP_OWNER = "base"


@functools.cache
def _module_sources() -> tuple[tuple[str, str, Path], ...]:
    # (repo, module, path) of every production Python file on the addons path
    sources = []
    for manifest in Manifest.get_all_addon_manifests():
        root = Path(manifest.path)
        if manifest.name.startswith("test_"):
            continue
        repo = lint_case.repo_of(str(root))
        for path in sorted(root.rglob("*.py")):
            if _SKIPPED_PARTS.intersection(path.relative_to(root).parts):
                continue
            sources.append((repo, manifest.name, path))
    return tuple(sources)


@functools.cache
def _tree(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError, UnicodeDecodeError:
        return None


def _calls(tree: ast.AST, names: frozenset[str]):
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in names
        ):
            yield node


def bare_sudo_findings(sources) -> dict[str, list[str]]:
    # sudo() and sudo(True): elevation to everything, which with_privilege
    # replaces wherever code acts on someone's behalf
    found: defaultdict[str, list[str]] = defaultdict(list)
    for repo, _module, path in sources:
        if (tree := _tree(path)) is None:
            continue
        for node in _calls(tree, frozenset({"sudo"})):
            if node.keywords or len(node.args) > 1:
                continue
            if node.args and not (
                isinstance(node.args[0], ast.Constant) and node.args[0].value is True
            ):
                continue
            found[repo].append(f"{path}:{node.lineno}")
    return found


def has_group_findings(sources) -> dict[str, list[str]]:
    found: defaultdict[str, list[str]] = defaultdict(list)
    for repo, _module, path in sources:
        if (tree := _tree(path)) is None:
            continue
        found[repo].extend(
            f"{path}:{node.lineno}" for node in _calls(tree, _GROUP_CHECKS)
        )
    return found


def _writes_membership(node: ast.AST) -> bool:
    # a membership written below the grants: group_ids on a user, or the users
    # of something named a group
    if isinstance(node, (ast.Assign, ast.AugAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return any(
            isinstance(target, ast.Attribute)
            and (
                target.attr == "group_ids"
                or (
                    target.attr == "user_ids"
                    and "group" in ast.unparse(target.value).lower()
                )
            )
            for target in targets
        )
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "write"
        and node.args
        and isinstance(node.args[0], ast.Dict)
    ):
        keys = {
            key.value
            for key in node.args[0].keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
        receiver = ast.unparse(node.func.value).lower()
        return "group_ids" in keys or ("user_ids" in keys and "group" in receiver)
    return False


def membership_write_findings(sources) -> list[str]:
    return [
        f"{path}:{node.lineno}"
        for repo, module, path in sources
        if module != _MEMBERSHIP_OWNER and (tree := _tree(path)) is not None
        for node in ast.walk(tree)
        if _writes_membership(node)
    ]


def _declared_privileges() -> frozenset[str]:
    # every res.groups record a module's data declares with is_privilege set
    names = set()
    for manifest in Manifest.get_all_addon_manifests():
        root = Path(manifest.path)
        for path in root.rglob("*.xml"):
            if _SKIPPED_PARTS.intersection(path.relative_to(root).parts):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "is_privilege" not in text:
                continue
            try:
                tree = etree.fromstring(text.encode())
            except etree.XMLSyntaxError:
                continue
            for record in tree.iter("record"):
                if record.get("model") != "res.groups":
                    continue
                flags = [
                    field
                    for field in record.iter("field")
                    if field.get("name") == "is_privilege"
                ]
                if flags and (flags[0].get("eval") or flags[0].text or "").strip() in (
                    "True",
                    "1",
                ):
                    xmlid = record.get("id")
                    names.add(xmlid if "." in xmlid else f"{manifest.name}.{xmlid}")
    return frozenset(names)


def privilege_findings(sources) -> list[str]:
    declared = _declared_privileges()
    findings = []
    for _repo, _module, path in sources:
        if (tree := _tree(path)) is None:
            continue
        for node in _calls(tree, frozenset({"with_privilege"})):
            for arg in node.args:
                if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                    findings.append(
                        f"{path}:{node.lineno} a privilege named at runtime"
                    )
                elif arg.value not in declared:
                    findings.append(
                        f"{path}:{node.lineno} {arg.value} is declared nowhere"
                    )
    return findings


class TestElevation(lint_case.LintCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sources = _module_sources()
        cls.repos = sorted({repo for repo, _module, _path in cls.sources})

    def test_bare_sudo_only_goes_down(self):
        found = bare_sudo_findings(self.sources)
        for repo in self.repos:
            with self.subTest(repo=repo):
                self.assert_ratchet(
                    found.get(repo, []),
                    f"bare_sudo_{repo.replace('-', '_')}",
                    f"bare sudo() call(s) in {repo}",
                    "Elevate to a named privilege: declare a res.groups record "
                    "with is_privilege and the ir.access rows it needs, and call "
                    "records.with_privilege('<module>.<name>', reason=...). sudo() "
                    "stays the kernel's.",
                )

    def test_has_group_only_goes_down(self):
        found = has_group_findings(self.sources)
        for repo in self.repos:
            with self.subTest(repo=repo):
                self.assert_ratchet(
                    found.get(repo, []),
                    f"has_group_{repo.replace('-', '_')}",
                    f"has_group check(s) in {repo}",
                    "Authority is ir.access rows (a permission, a guard, a "
                    "privilege), not a group test in code.",
                )

    def test_memberships_are_granted_not_written(self):
        self.assert_ratchet(
            membership_write_findings(
                source for source in self.sources if source[0] == "odoo"
            ),
            "grant_membership_write",
            "membership write(s) outside base",
            "Give or end a group through res.users.grant._grant / _revoke with a "
            "cause, so the grant says why it exists.",
        )

    def test_every_privilege_named_is_declared(self):
        self.assert_ratchet(
            privilege_findings(self.sources),
            "privilege_declared",
            "with_privilege() name(s) no module declares",
            "Declare the privilege as a res.groups record with "
            '<field name="is_privilege" eval="True"/> and give it its '
            "ir.access rows.",
        )


class TestElevationGatesSeeTheirFaults(lint_case.LintCase):
    def _sources(self, text):
        path = Path(self.id().rsplit(".", 1)[-1] + ".py")
        _tree.cache_clear()
        tree = ast.parse(text)
        return [("odoo", "planted", path)], tree

    def _scan(self, function, text):
        sources, tree = self._sources(text)
        original = _tree
        globals()["_tree"] = lambda path: tree
        try:
            return function(sources)
        finally:
            globals()["_tree"] = original

    def test_a_bare_sudo(self):
        found = self._scan(bare_sudo_findings, "x.sudo()\ny.sudo(True)\nz.sudo(False)")
        self.assertEqual(len(found["odoo"]), 2)

    def test_a_group_check(self):
        found = self._scan(has_group_findings, "u.has_group('a.b')\nu._has_group('c')")
        self.assertEqual(len(found["odoo"]), 2)

    def test_a_membership_write(self):
        text = (
            "user.group_ids = [1]\n"
            "group.write({'user_ids': [(4, 1)]})\n"
            "channel.write({'user_ids': [(4, 1)]})\n"
        )
        self.assertEqual(len(self._scan(membership_write_findings, text)), 2)

    def test_an_undeclared_privilege(self):
        found = self._scan(privilege_findings, "r.with_privilege('nope.nothing')")
        self.assertEqual(len(found), 1)
