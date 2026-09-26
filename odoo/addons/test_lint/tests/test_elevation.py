import ast
import functools
import re
from collections import defaultdict
from pathlib import Path

from lxml import etree

from odoo.models import BaseModel
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


_MODEL_BASES = frozenset(
    {"Model", "TransientModel", "AbstractModel"}
    | {f"models.{base}" for base in ("Model", "TransientModel", "AbstractModel")}
)
_ELEVATED_WRITES = frozenset({"write", "create", "unlink", "copy"})
# an override of these that calls its super() has the ORM check the caller's
# own access to the records, and an AccessError rolls back what it wrote
# through elevation
_CHECKED_CRUD = frozenset(
    {"create", "write", "unlink", "copy", "action_archive", "action_unarchive"}
)
_ACCESS_CHECKS = frozenset(
    {"check_access", "check_access_rights", "check_access_rule", "has_access"}
)
_ROLE_CHECKS = _GROUP_CHECKS | {"user_has_groups", "is_admin", "is_system"}
_SAME_RECORDS = frozenset(
    {"filtered", "filtered_domain", "sorted", "with_context", "with_company", "exists"}
)
# what these return is no recordset, so the elevation stops travelling there
_VALUE_ATTRS = frozenset({"id", "ids", "_ids", "display_name"})
_VALUE_CALLS = frozenset(
    {"read", "search_read", "search_count", "read_group", "_read_group", "get_param"}
)
_SQL_RUNNERS = frozenset({"execute", "executemany", "execute_query"})
_SELF_WRITES = frozenset({"write", "unlink"})
_SQL_DML = re.compile(
    r"\b(INSERT\s+INTO|UPDATE\s+\S+\s+SET|DELETE\s+FROM)\b", re.IGNORECASE
)


def _is_superuser(node: ast.AST) -> bool:
    if isinstance(node, ast.Name | ast.Attribute):
        return ast.unparse(node).endswith("SUPERUSER_ID")
    if isinstance(node, ast.Constant):
        return node.value == 1 and not isinstance(node.value, bool)
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "ref"
        and bool(node.args)
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "base.user_root"
    )


def _elevates(call: ast.Call) -> bool:
    # sudo() / sudo(<anything but a false constant>), with_privilege, the
    # superuser as user, and an environment built with su or as the superuser
    for keyword in call.keywords:
        if keyword.arg == "su" and not (
            isinstance(keyword.value, ast.Constant) and not keyword.value.value
        ):
            return True
        if keyword.arg == "user" and _is_superuser(keyword.value):
            return True
    func = call.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    if name == "sudo":
        flag = call.args[0] if call.args else None
        if flag is None and call.keywords:
            flag = call.keywords[0].value
        return not (isinstance(flag, ast.Constant) and not flag.value)
    if name == "with_privilege":
        return True
    if name == "with_user":
        return bool(call.args) and _is_superuser(call.args[0])
    if name == "Environment":
        return len(call.args) > 1 and _is_superuser(call.args[1])
    return False


class _Flow:
    # which names of one method hold an elevated recordset or environment, and
    # which hold nothing but what the caller passed: JSON carries no recordset,
    # so an elevation rooted at a parameter is never reached through RPC
    def __init__(self, function: ast.FunctionDef):
        self.function = function
        arguments = function.args
        params = [
            arg.arg
            for arg in (
                *arguments.posonlyargs,
                *arguments.args,
                *arguments.kwonlyargs,
                *filter(None, (arguments.vararg, arguments.kwarg)),
            )
        ]
        self.self_name = params[0] if params else "self"
        self.elevated: set[str] = set()
        self.external = set(params[1:])
        self.same: set[str] = {self.self_name}
        bindings = list(self._bindings())
        by_name: defaultdict[str, list[ast.AST]] = defaultdict(list)
        for name, value in bindings:
            by_name[name].append(value)
        changed = True
        while changed:
            external = set(params[1:]) - by_name.keys()
            external |= {
                name
                for name, values in by_name.items()
                if all(map(self._is_external, values))
            }
            changed, self.external = external != self.external, external
        changed = True
        while changed:
            changed = False
            for name, value in bindings:
                if name not in self.elevated and self.is_elevated(value):
                    self.elevated.add(name)
                    changed = True
                if name not in self.same and self._is_same(value):
                    self.same.add(name)
                    changed = True

    def _bindings(self):
        for node in ast.walk(self.function):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        yield target.id, node.value
                    elif isinstance(target, ast.Tuple) and isinstance(
                        node.value, ast.Tuple
                    ):
                        for name, value in zip(
                            target.elts, node.value.elts, strict=False
                        ):
                            if isinstance(name, ast.Name):
                                yield name.id, value
            elif isinstance(node, ast.AnnAssign | ast.NamedExpr) and isinstance(
                node.target, ast.Name
            ):
                if node.value is not None:
                    yield node.target.id, node.value
            elif isinstance(node, ast.For | ast.comprehension) and isinstance(
                node.target, ast.Name
            ):
                yield node.target.id, node.iter
            elif isinstance(node, ast.With):
                for item in node.items:
                    if isinstance(item.optional_vars, ast.Name):
                        yield item.optional_vars.id, item.context_expr

    def _branches(self, node: ast.AST) -> list[ast.AST]:
        if isinstance(node, ast.IfExp):
            return [*self._branches(node.body), *self._branches(node.orelse)]
        if isinstance(node, ast.BoolOp):
            return [branch for value in node.values for branch in self._branches(value)]
        return [node]

    def _root(self, node: ast.AST) -> tuple[ast.AST, bool]:
        # the name a receiver chain starts from, and whether a link elevates
        elevated = False
        while True:
            if isinstance(node, ast.Call):
                if _elevates(node) or (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "with_env"
                    and node.args
                    and self.is_elevated(node.args[0])
                ):
                    elevated = True
                node = node.func
            elif isinstance(node, ast.Attribute | ast.Subscript):
                node = node.value
            else:
                return node, elevated

    def _is_external(self, value: ast.AST) -> bool:
        return all(
            isinstance(root, ast.Name) and root.id in self.external
            for root, _elevated in map(self._root, self._branches(value))
        )

    def is_elevated(self, value: ast.AST) -> bool:
        for branch in self._branches(value):
            if isinstance(branch, ast.Attribute) and branch.attr in _VALUE_ATTRS:
                continue
            if (
                isinstance(branch, ast.Call)
                and isinstance(branch.func, ast.Attribute)
                and branch.func.attr in _VALUE_CALLS
            ):
                continue
            root, elevated = self._root(branch)
            if isinstance(root, ast.Name) and root.id in self.external:
                continue
            if elevated or (isinstance(root, ast.Name) and root.id in self.elevated):
                return True
        return False

    def _is_same(self, node: ast.AST) -> bool:
        # the records the call was made on, narrowed or recontextualised
        while (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _SAME_RECORDS
        ):
            node = node.func.value
        return isinstance(node, ast.Name) and node.id in self.same

    def _writes_elevated(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Call):
            return (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in _ELEVATED_WRITES
                and self.is_elevated(node.func.value)
            )
        if not isinstance(node, ast.Assign | ast.AugAssign):
            return False
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return any(
            isinstance(target, ast.Attribute) and self.is_elevated(target.value)
            for target in targets
        )

    def first_elevated_write(self) -> tuple[int, int] | None:
        writes = [
            _position(node)
            for node in ast.walk(self.function)
            if self._writes_elevated(node)
        ]
        if (sql := self._first_sql_write()) is not None:
            writes.append(sql)
        return min(writes, default=None)

    def _first_sql_write(self) -> tuple[int, int] | None:
        # raw DML answers to no ACL at all
        if not any(
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _SQL_DML.search(node.value)
            for node in ast.walk(self.function)
        ):
            return None
        return min(
            (
                _position(node)
                for node in ast.walk(self.function)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _SQL_RUNNERS
            ),
            default=None,
        )

    def _checks_right(self, node: ast.AST) -> bool:
        # a role test, or an access check other than "read" on records that
        # are not elevated, which would pass it whatever the caller holds
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            return False
        if node.func.attr in _ROLE_CHECKS:
            return True
        operation = node.args[0] if node.args else None
        return (
            node.func.attr in _ACCESS_CHECKS
            and not (isinstance(operation, ast.Constant) and operation.value == "read")
            and not self.is_elevated(node.func.value)
        )

    def _writes_own(self, node: ast.AST) -> bool:
        # a write of the records the call was made on, under the caller's own
        # access
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            return node.func.attr in _SELF_WRITES and self._same_unelevated(
                node.func.value
            )
        return isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Attribute) and self._same_unelevated(target.value)
            for target in node.targets
        )

    def _same_unelevated(self, node: ast.AST) -> bool:
        return not self.is_elevated(node) and self._is_same(node)

    def is_guarded(self, first_write: tuple[int, int]) -> bool:
        # A check guards only from before the first elevated write, so nothing
        # (the database or a remote service) is touched for a refused caller.
        # A write of the call's own records guards wherever it stands: the
        # ORM refuses it and the RPC transaction rolls back what the elevation
        # wrote before it, as with a CRUD override calling super().
        return any(
            (_position(node) < first_write and self._checks_right(node))
            or self._writes_own(node)
            for node in ast.walk(self.function)
            if hasattr(node, "lineno")
        )


def _position(node: ast.AST) -> tuple[int, int]:
    return node.lineno, node.col_offset


def _model_classes(tree: ast.AST):
    for node in getattr(tree, "body", ()):
        if isinstance(node, ast.ClassDef) and any(
            ast.unparse(base) in _MODEL_BASES for base in node.bases
        ):
            yield node


def _class_constant(cls: ast.ClassDef, name: str) -> ast.AST | None:
    for node in cls.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == name
        ):
            return node.value
    return None


def _strings(node: ast.AST | None) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.List | ast.Tuple):
        return [
            element.value
            for element in node.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        ]
    return []


def _model_names(cls: ast.ClassDef) -> tuple[str | None, list[str]]:
    inherits = _strings(_class_constant(cls, "_inherit"))
    names = _strings(_class_constant(cls, "_name"))
    name = names[0] if names else (inherits[0] if inherits else None)
    return name, [parent for parent in inherits if parent != name]


def _decorators(function: ast.FunctionDef) -> set[str]:
    return {ast.unparse(decorator) for decorator in function.decorator_list}


def _verb_doors(cls: ast.ClassDef) -> set[str]:
    verbs = _class_constant(cls, "_access_verbs")
    if not isinstance(verbs, ast.Dict):
        return set()
    return {
        method
        for verb in verbs.values
        if isinstance(verb, ast.Call)
        for keyword in verb.keywords
        if keyword.arg in ("methods", "checkpoints")
        for method in _strings(keyword.value)
    }


def _closed(model: str, own: dict[str, set[str]], parents: dict[str, set[str]]):
    seen, stack, names = set(), [model], set()
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        names |= own.get(current, set())
        stack.extend(parents.get(current, ()))
    return names


def _extends(function: ast.FunctionDef) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == function.name
        and isinstance(node.func.value, ast.Call)
        and isinstance(node.func.value.func, ast.Name)
        and node.func.value.func.id == "super"
        for node in ast.walk(function)
    )


@functools.cache
def _kernel_private() -> frozenset[str]:
    # what BaseModel declares @api.private is private on every model
    return frozenset(
        name
        for cls in BaseModel.__mro__
        for name, value in vars(cls).items()
        if getattr(value, "_api_private", False)
    )


def public_elevation_findings(sources) -> dict[str, list[str]]:
    # a public model method, so an RPC entry point, that elevates and writes
    # through the elevation without asking the caller's own right in the call
    classes = []
    parents: defaultdict[str, set[str]] = defaultdict(set)
    private: defaultdict[str, set[str]] = defaultdict(set)
    kernel_private = _kernel_private()
    doors: defaultdict[str, set[str]] = defaultdict(set)
    for repo, _module, path in sources:
        if (tree := _tree(path)) is None:
            continue
        for cls in _model_classes(tree):
            model, inherits = _model_names(cls)
            if model is None:
                continue
            parents[model].update(inherits)
            doors[model] |= _verb_doors(cls)
            private[model] |= {
                function.name
                for function in cls.body
                if isinstance(function, ast.FunctionDef)
                and _decorators(function) & {"api.private", "private"}
            }
            classes.append((repo, path, model, cls))
    found: defaultdict[str, list[str]] = defaultdict(list)
    for repo, path, model, cls in classes:
        closed_private = _closed(model, private, parents)
        closed_doors = _closed(model, doors, parents)
        for function in cls.body:
            if (
                not isinstance(function, ast.FunctionDef)
                or function.name.startswith("_")
                or (function.name in _CHECKED_CRUD and _extends(function))
                or function.name in closed_private
                or function.name in kernel_private
                or function.name in closed_doors
                or _decorators(function) & {"staticmethod", "classmethod", "property"}
            ):
                continue
            flow = _Flow(function)
            write = flow.first_elevated_write()
            if write is not None and not flow.is_guarded(write):
                found[repo].append(f"{path}:{function.lineno} {model}.{function.name}")
    return found


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

    def test_public_elevation_only_goes_down(self):
        found = public_elevation_findings(self.sources)
        for repo in self.repos:
            with self.subTest(repo=repo):
                self.assert_ratchet(
                    found.get(repo, []),
                    f"public_elevation_{repo.replace('-', '_')}",
                    f"public method(s) writing through an elevation in {repo}",
                    "A public model method is an RPC entry point any user calls "
                    "on any ids: ask the caller's own right in it "
                    "(self.check_access('write'), a group, a write of self), make "
                    "it @api.private when no client calls it, or make it a door of "
                    "a models.Verb.",
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

    def test_a_public_elevated_write(self):
        text = """
from odoo import api, models


class Planted(models.Model):
    _name = "planted.model"
    _access_verbs = {"post": models.Verb(methods=("action_door",))}

    def action_open(self):
        self.sudo().write({"state": "done"})

    def action_local(self):
        records = self.with_privilege("planted.privilege")
        records.partner_id.write({"name": "x"})

    def action_env(self):
        env = self.env(su=True)
        env["res.partner"].create({})

    def action_superuser(self):
        self.with_user(SUPERUSER_ID).unlink()

    def action_sql(self):
        self.env.cr.execute("UPDATE planted_model SET state = 'done'")

    def action_assigned(self):
        for record in self.sudo():
            record.state = "done"

    def action_read_checked(self):
        self.check_access("read")
        self.sudo().write({})

    @api.model
    def action_by_id(self, record_id):
        self.env["planted.model"].browse(record_id).sudo().unlink()

    def action_checked(self):
        self.check_access("write")
        self.sudo().write({})

    def action_checked_late(self):
        self.sudo().write({})
        self.check_access("write")

    def action_checked_elevated(self):
        self.sudo().check_access("write")
        self.sudo().write({})

    def action_target_checked(self):
        partner = self.partner_id
        partner.check_access("write")
        partner.sudo().write({})

    def action_grouped(self):
        if not self.env.user.has_group("base.group_system"):
            return
        self.sudo().write({})

    def action_self_written(self):
        self.write({"state": "done"})
        self.sudo().partner_id.write({})

    def action_self_written_late(self):
        self.sudo().partner_id.write({})
        self.state = "done"

    def action_door(self):
        self.sudo().write({})

    @api.private
    def action_private(self):
        self.sudo().write({})

    def _action_underscore(self):
        self.sudo().write({})

    @api.model
    def action_by_record(self, record):
        record.sudo().write({})

    def action_elevated_read(self):
        return self.sudo().read(["state"])

    def action_unelevated(self):
        self.sudo(False).write({})

    def write(self, vals):
        self.sudo().partner_id.write({})
        return super().write(vals)

    def init(self):
        self.env.cr.execute("UPDATE planted_model SET state = 'draft'")


class PlantedExtension(models.Model):
    _inherit = "planted.model"

    def action_private(self):
        self.sudo().write({})
"""
        found = self._scan(public_elevation_findings, text)["odoo"]
        self.assertEqual(
            sorted(finding.rsplit(".", 1)[-1] for finding in found),
            [
                "action_assigned",
                "action_by_id",
                "action_checked_elevated",
                "action_checked_late",
                "action_env",
                "action_local",
                "action_open",
                "action_read_checked",
                "action_sql",
                "action_superuser",
            ],
        )

    def test_an_undeclared_privilege(self):
        found = self._scan(privilege_findings, "r.with_privilege('nope.nothing')")
        self.assertEqual(len(found), 1)
