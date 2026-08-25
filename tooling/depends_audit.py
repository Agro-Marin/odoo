"""Computes that read a field they do not declare, resolved through relations.

Run under `odoo shell`, against the WIDEST registry available — the finding this
tool was packaged for (`c6799a29775`, `mail.tracking.duration.mixin`) was
invisible with only `mail` installed, because the mixin has no concrete consumer
there and nothing reached the compute. It surfaced on 191 modules.

    echo 'from tooling.depends_audit import main; main(env)' \
        | odoo-bin shell -c <conf> -d <db> --no-http

    DEPENDS_TARGET=/addons/sale/ ...        # narrow it; default is /addons/

Findings come in two tiers, which is the whole point of the resolution:

    A  root not watched at all   the compute reads `x.y` and declares neither
    B  root watched, leaf not    it declares `x` and reads `x.y`

NOT THE SAME QUESTION AS `odoo/tools/depends_audit.py`, which is wired into the
framework's own tests. That one walks BYTECODE and reports the attributes a
compute reads; this one walks the AST and then RESOLVES each read through the
registry, so it can tell a declared root from a declared leaf and can follow a
path across comodels. Measured on one registry (90 modules, loyalty and its
dependencies): 322 findings here against 30 there, sharing 18 — twelve that only
the bytecode walk sees, and some three hundred that only this one does. Neither
subsumes the other; a `depends` question worth asking gets asked of both.

IT DOES NOT GATE ANYTHING, and cannot: the answer depends on what is installed,
so a floor over it would measure the database rather than the tree. It is an
investigative tool, like `tooling/testbaseline` and `tooling/patchorder`.
"""


import ast
import inspect
import os
import textwrap
from collections import defaultdict

TARGET = os.environ.get("DEPENDS_TARGET", "/addons/")
SKIP_PATHS = ("/test_", "/addons/test", "_test/")

PASSTHROUGH = frozenset(
    {
        "sudo",
        "with_context",
        "with_user",
        "with_env",
        "with_company",
        "with_prefetch",
        "exists",
        "filtered",
        "filtered_domain",
        "sorted",
        "browse",
        "_origin",
    }
)
IGNORED_ATTRS = frozenset(
    {
        "id",
        "ids",
        "_name",
        "_origin",
        "env",
        "_fields",
        "_table",
        "display_name",
    }
)


def _field_of(model, name):
    return model._fields.get(name) if model is not None else None


def _comodel(env, model, fname):
    field = _field_of(model, fname)
    if field is not None and field.relational:
        return env.get(field.comodel_name)
    return None


def _join(prefix, part):
    return f"{prefix}.{part}" if prefix else part


class _Reads(ast.NodeVisitor):
    def __init__(self, env, model, self_name, depth=0, inlined=None):
        self.env = env
        self.model = model
        self.depth = depth
        self.inlined = inlined if inlined is not None else set()
        self.bindings = {self_name: (model, "")}
        self.paths = set()
        self.stores = set()

    def _bind(self, target, value_node):
        ref = self._ref_of(value_node)
        if ref is not None and isinstance(target, ast.Name):
            self.bindings[target.id] = ref

    def visit_For(self, node):
        self._bind(node.target, node.iter)
        self.generic_visit(node)

    def visit_Assign(self, node):
        for target in node.targets:
            if isinstance(target, ast.Attribute):
                self.stores.add(id(target))
            self._bind(target, node.value)
        self.generic_visit(node)

    def _bind_comprehension(self, node):
        for generator in node.generators:
            self._bind(generator.target, generator.iter)

    def visit_ListComp(self, node):
        self._bind_comprehension(node)
        self.generic_visit(node)

    visit_SetComp = visit_GeneratorExp = visit_ListComp

    def visit_DictComp(self, node):
        self._bind_comprehension(node)
        self.generic_visit(node)

    def _ref_of(self, node):
        if isinstance(node, ast.Name):
            return self.bindings.get(node.id)
        if isinstance(node, ast.Subscript):
            return self._ref_of(node.value)
        if isinstance(node, ast.Call):
            func = node.func
            if not isinstance(func, ast.Attribute):
                return None
            if func.attr in PASSTHROUGH:
                return self._ref_of(func.value)
            if func.attr == "mapped" and node.args:
                base = self._ref_of(func.value)
                arg = node.args[0]
                if (
                    base
                    and isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                ):
                    return self._walk(base, arg.value.split("."))
            if self.depth < 1:
                self._inline_helper(func)
            return None
        if isinstance(node, ast.Attribute):
            base = self._ref_of(node.value)
            return self._walk(base, [node.attr]) if base else None
        return None

    def _walk(self, ref, parts):
        model, prefix = ref
        for part in parts:
            if part in IGNORED_ATTRS or _field_of(model, part) is None:
                return None
            prefix = _join(prefix, part)
            self.paths.add(prefix)
            model = _comodel(self.env, model, part)
            if model is None:
                return None
        return (model, prefix)

    def _inline_helper(self, func_node):
        ref = self._ref_of(func_node.value)
        if ref is None:
            return
        model, prefix = ref
        method = getattr(type(model), func_node.attr, None)
        if method is None or not callable(method):
            return
        try:
            path = inspect.getsourcefile(method)
            source = inspect.getsource(method)
        except TypeError, OSError:
            return
        if not path or TARGET not in path:
            return
        key = (path, func_node.attr, prefix)
        if key in self.inlined:
            return
        self.inlined.add(key)
        try:
            tree = ast.parse(textwrap.dedent(source))
        except SyntaxError:
            return
        func = tree.body[0]
        if not getattr(func, "args", None) or not func.args.args:
            return
        sub = _Reads(
            self.env,
            model,
            func.args.args[0].arg,
            depth=self.depth + 1,
            inlined=self.inlined,
        )
        sub.bindings[func.args.args[0].arg] = (model, prefix)
        sub.visit(func)
        self.paths |= sub.paths

    def visit_Attribute(self, node):
        if id(node) not in self.stores:
            self._ref_of(node)
        self.generic_visit(node)


def _covered(read, declared):
    return any(read == dep or dep.startswith(read + ".") for dep in declared)


def _read_is_safe(env, model, read, effective, seen=None):
    if _covered(read, effective):
        return True
    parts = read.split(".")
    owner = model
    for part in parts[:-1]:
        owner = _comodel(env, owner, part)
        if owner is None:
            return False
    field = owner._fields.get(parts[-1])
    if field is None or not (field.compute or field.related):
        return False
    if field.store and not field.readonly:
        return False
    seen = seen if seen is not None else set()
    prefix = ".".join(parts[:-1])
    # KEYED ON THE FIELD, NOT ON THE PATH THAT REACHED IT. The cycle this guard
    # exists to stop lives in the (model, field) dependency graph, but the key
    # used to carry `prefix` too -- and `prefix` GROWS on every recursion, since
    # each level appends through `_join`. So a field revisited one hop deeper got
    # a fresh key, the guard never fired, and the walk ran until the interpreter
    # stopped it. `RecursionError: maximum recursion depth exceeded`, on a
    # registry no larger than loyalty and its dependencies.
    #
    # Kept as an on-stack marker rather than a visited set: a field legitimately
    # reached twice down two different branches is not a cycle, and answering
    # False for the second one would invent a finding. It is removed on the way
    # back out.
    key = (owner._name, parts[-1])
    if key in seen:
        return False
    seen.add(key)
    try:
        deps = env.registry.field_depends[field] or ()
        return bool(deps) and all(
            _read_is_safe(env, model, _join(prefix, dep), effective, seen)
            for dep in deps
        )
    finally:
        seen.discard(key)


def _expand(env, model, declared):
    out, queue = set(declared), list(declared)
    while queue:
        dep = queue.pop()
        if "." in dep:
            continue
        field = model._fields.get(dep)
        if field is None or not field.compute:
            continue
        for sub in env.registry.field_depends[field] or ():
            if sub not in out:
                out.add(sub)
                queue.append(sub)
    return out


def audit(env):
    findings = []
    seen = set()
    for model_name in sorted(env.registry):
        model = env[model_name]
        for fname, field in sorted(model._fields.items()):
            if not field.compute or field.related or not isinstance(field.compute, str):
                continue
            method = getattr(type(model), field.compute, None)
            if method is None:
                continue
            try:
                source_file = inspect.getsourcefile(method)
                source = inspect.getsource(method)
                lineno = inspect.getsourcelines(method)[1]
            except TypeError, OSError:
                continue
            if not source_file or TARGET not in source_file:
                continue
            if any(skip in source_file for skip in SKIP_PATHS):
                continue
            key = (source_file, field.compute)
            if key in seen:
                continue
            seen.add(key)
            try:
                tree = ast.parse(textwrap.dedent(source))
            except SyntaxError:
                continue
            func = tree.body[0]
            self_name = func.args.args[0].arg if func.args.args else "self"
            reads = _Reads(env, model, self_name)
            reads.visit(func)

            declared = set(env.registry.field_depends[field] or ())
            effective = _expand(env, model, declared)
            targets = {
                other
                for other, other_field in model._fields.items()
                if other_field.compute == field.compute
            }
            missing = [
                path
                for path in sorted(reads.paths)
                if path.split(".")[0] not in targets
                and not _read_is_safe(env, model, path, effective)
            ]
            if not missing:
                continue
            unwatched = [
                path
                for path in missing
                if not any(dep.split(".")[0] == path.split(".")[0] for dep in effective)
            ]
            findings.append(
                {
                    "model": model_name,
                    "field": fname,
                    "compute": field.compute,
                    "file": source_file.split("/addons/")[-1],
                    "line": lineno,
                    "stored": bool(field.store),
                    "declared": sorted(declared),
                    "unwatched": unwatched,
                    "leaf_only": [path for path in missing if path not in unwatched],
                }
            )
    return findings


def main(env):
    grouped = defaultdict(list)
    for finding in audit(env):
        grouped[(finding["file"], finding["compute"], finding["line"])].append(finding)

    for title, key in (
        ("A -- ROOT NOT WATCHED AT ALL", "unwatched"),
        ("B -- root watched, leaf not", "leaf_only"),
    ):
        tier = {k: g for k, g in grouped.items() if any(f[key] for f in g)}
        print(f"\n{'=' * 70}\nTIER {title}: {len(tier)} compute methods\n{'=' * 70}\n")
        for (file, compute, line), group in sorted(tier.items()):
            stored = "STORED" if any(f["stored"] for f in group) else "unstored"
            print(f"{file}:{line}  {compute}  [{stored}]  ({group[0]['model']})")
            print(f"    declared: {group[0]['declared']}")
            for finding in group:
                if finding[key]:
                    print(f"    {finding['field']}  <- reads {finding[key]}")
            print()
