import ast
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field

CURSOR_EXPRESSIONS = frozenset(
    {
        "self.env.cr",
        "self.cr",
        "self._cr",
        "cr",
        "env.cr",
        "odoo.tools",
        "tools",
    }
)
ATTRIBUTE_WHITELIST = ("_table", "name", "lang", "id", "get_lang.code")

FUNCTION_WHITELIST = frozenset(
    {
        "create",
        "read",
        "write",
        "browse",
        "select",
        "get",
        "strip",
        "items",
        "_select",
        "_from",
        "_where",
        "any",
        "join",
        "split",
        "tuple",
        "get_sql",
        "search",
        "list",
        "set",
        "next",
        "SQL",
    }
)


@dataclass
class Violation:
    lineno: int
    col_offset: int
    message: str = ""


@dataclass
class SqlInjectionChecker:
    filepath: str

    _function_defs: dict[str, list[ast.FunctionDef]] = field(
        default_factory=lambda: defaultdict(list),
        init=False,
    )
    _callsites: dict[str, list[tuple[int | None, bool, ast.Call]]] = field(
        default_factory=lambda: defaultdict(list),
        init=False,
    )
    _root_call: ast.Call | None = field(default=None, init=False)
    _const_def_cache: dict = field(default_factory=dict, init=False)
    _assign_cache: dict[int, dict[str, list[ast.AST]]] = field(
        default_factory=dict, init=False
    )
    _assert_cache: dict[int, set[str]] = field(default_factory=dict, init=False)

    _module_const_cache: dict[int, dict[str, ast.expr]] = field(
        default_factory=dict, init=False
    )
    _resolving_names: set[tuple[int, str]] = field(default_factory=set, init=False)
    _resolving_nodes: set[int] = field(default_factory=set, init=False)

    def check_nodes(self, nodes: list[ast.AST]) -> Iterator[Violation]:
        for node in nodes:
            match node:
                case ast.Call():
                    yield from self._visit_call(node)
                case ast.FunctionDef() | ast.AsyncFunctionDef():
                    yield from self._visit_functiondef(node)

    def _visit_call(self, node: ast.Call) -> Iterator[Violation]:
        if self._check_sql_injection_risky(node):
            yield Violation(node.lineno, node.col_offset)

    def _visit_functiondef(self, node: ast.FunctionDef) -> Iterator[Violation]:
        self._function_defs[node.name].append(node)

        for position, const_args, call in self._callsites[node.name]:
            if not self._is_const_def(node, position=position, const_args=const_args):
                yield Violation(
                    node.lineno,
                    node.col_offset,
                    f"because it is used to build a query at {self.filepath}:{call.lineno}",
                )

    def _check_sql_injection_risky(self, node: ast.Call) -> bool:
        if not node.args:
            return False

        match node.func:
            case ast.Attribute(attr=attr) if attr in (
                "execute",
                "executemany",
                "SQL",
            ):
                if self._get_cursor_name(node.func) not in CURSOR_EXPRESSIONS:
                    return False
            case ast.Name(id="SQL"):
                pass
            case _:
                return False

        first_arg = node.args[0]
        result = self._check_concatenation(first_arg)
        if result is not None:
            return result
        return True

    def _check_concatenation(self, node: ast.expr) -> bool | None:
        node = self._resolve(node)

        if self._allowable(node):
            return False

        if id(node) in self._resolving_nodes:
            return None
        self._resolving_nodes.add(id(node))
        try:
            return self._check_concatenation_inner(node)
        finally:
            self._resolving_nodes.discard(id(node))

    def _check_concatenation_inner(self, node: ast.expr) -> bool | None:
        match node:
            case ast.BinOp(op=ast.Mod() | ast.Add()):
                match node.right:
                    case ast.Tuple(elts=elts):
                        if not all(map(self._allowable, elts)):
                            return True
                    case ast.Dict(values=values):
                        if not all(map(self._allowable, values)):
                            return True
                    case _ if not self._allowable(node.right):
                        return True
                return self._check_concatenation(node.left)

            case ast.Call(func=ast.Attribute(attr="format")):
                return not (
                    all(map(self._allowable, node.args or []))
                    and all(self._allowable(kw.value) for kw in (node.keywords or []))
                )

            case ast.JoinedStr(values=values):
                return not all(
                    self._allowable(fv.value)
                    for fv in values
                    if isinstance(fv, ast.FormattedValue)
                )

        return None

    def _resolve(self, node: ast.expr) -> ast.expr:
        if isinstance(node, ast.Name):
            scope = self._find_enclosing_scope(node)
            if scope is not None:
                for target_node in self._find_assignments(scope, node.id):
                    if isinstance(target_node, ast.Assign):
                        if any(isinstance(t, ast.Tuple) for t in target_node.targets):
                            continue
                        return target_node.value
        return node

    def _is_constexpr(
        self,
        node: ast.expr,
        *,
        args_allowed: bool = False,
        position: int | None = None,
    ) -> bool:
        match node:
            case ast.Constant():
                return True

            case ast.List(elts=elts) | ast.Set(elts=elts):
                return self._all_const(elts, args_allowed=args_allowed)

            case ast.Tuple(elts=elts):
                if position is not None:
                    return self._is_constexpr(
                        elts[position],
                        args_allowed=args_allowed,
                    )
                return self._all_const(elts, args_allowed=args_allowed)

            case ast.Dict(keys=keys, values=values):
                return all(
                    self._is_constexpr(k, args_allowed=args_allowed)
                    and self._is_constexpr(v, args_allowed=args_allowed)
                    for k, v in zip(keys, values, strict=False)
                )

            case ast.Starred(value=value):
                return self._is_constexpr(
                    value,
                    args_allowed=args_allowed,
                    position=position,
                )

            case ast.BinOp(op=op, left=left, right=right):
                left_ok = self._is_constexpr(left, args_allowed=args_allowed)
                if (
                    isinstance(op, ast.Mod)
                    and isinstance(left, ast.Constant)
                    and isinstance(left.value, str)
                    and "%d" in left.value
                    and "%s" not in left.value
                ):
                    return True
                right_ok = self._is_constexpr(right, args_allowed=args_allowed)
                return left_ok and right_ok

            case ast.Name(id=name):
                return self._check_name_constexpr(
                    node,
                    name,
                    args_allowed=args_allowed,
                )

            case ast.JoinedStr(values=values):
                return self._all_const(
                    (
                        fv.value
                        for fv in values
                        if isinstance(fv, ast.FormattedValue)
                        if not (
                            isinstance(fv.value, ast.Attribute)
                            and fv.value.attr.startswith("_")
                        )
                    ),
                    args_allowed=args_allowed,
                    position=position,
                )

            case ast.Call(func=ast.Attribute(attr="append"), args=[first_arg]):
                return self._is_constexpr(first_arg)

            case ast.Call(func=ast.Attribute(attr="format", value=receiver)):
                return (
                    self._is_constexpr(receiver, args_allowed=args_allowed)
                    and self._all_const(node.args, args_allowed=args_allowed)
                    and self._all_const(
                        (kw.value for kw in node.keywords or []),
                        args_allowed=args_allowed,
                    )
                )

            case ast.Call():
                old_root = self._root_call
                if self._root_call is None:
                    self._root_call = node
                try:
                    return self._evaluate_function_call(
                        node,
                        args_allowed=args_allowed,
                        position=position,
                    )
                finally:
                    self._root_call = old_root

            case ast.IfExp(body=body, orelse=orelse):
                return self._is_constexpr(
                    body, args_allowed=args_allowed
                ) and self._is_constexpr(orelse, args_allowed=args_allowed)

            case ast.Subscript(value=value):
                return self._is_constexpr(value, args_allowed=args_allowed)

            case ast.BoolOp(values=values):
                return self._all_const(values, args_allowed=args_allowed)

            case ast.Attribute():
                return self._check_attribute_whitelist(node)

        return False

    def _all_const(self, nodes, *, args_allowed=False, position=None) -> bool:
        return all(
            self._is_constexpr(n, args_allowed=args_allowed, position=position)
            for n in nodes
        )

    def _check_name_constexpr(
        self,
        node: ast.Name,
        name: str,
        *,
        args_allowed: bool = False,
    ) -> bool:
        scope = self._find_enclosing_scope(node)
        if scope is None:
            return False

        key = (id(scope), name)
        if key in self._resolving_names:
            return False
        self._resolving_names.add(key)
        try:
            return self._resolve_name(node, name, scope, args_allowed=args_allowed)
        finally:
            self._resolving_names.discard(key)

    def _resolve_name(
        self,
        node: ast.Name,
        name: str,
        scope: ast.AST,
        *,
        args_allowed: bool = False,
    ) -> bool:
        assigned_results: list[bool] = []

        for assign_node in self._find_assignments(scope, name):
            match assign_node:
                case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.arg():
                    assigned_results.append(args_allowed)

                case ast.Assign(value=value, targets=targets):
                    target_position = self._find_tuple_position(targets, name)
                    if target_position is not None:
                        assigned_results.append(
                            self._is_constexpr(
                                value,
                                args_allowed=args_allowed,
                                position=target_position,
                            )
                        )
                    else:
                        assigned_results.append(
                            self._is_constexpr(value, args_allowed=args_allowed)
                        )

                case ast.AugAssign(value=value):
                    assigned_results.append(
                        self._is_constexpr(value, args_allowed=args_allowed)
                    )

                case ast.For(iter=iter_node):
                    assigned_results.append(
                        self._is_constexpr(iter_node, args_allowed=args_allowed)
                    )

                case ast.comprehension(iter=iter_node):
                    assigned_results.append(
                        self._is_constexpr(iter_node, args_allowed=args_allowed)
                    )

        if not assigned_results and (value := self._module_constant(node, name)):
            return self._is_constexpr(value, args_allowed=args_allowed)

        if assigned_results and all(assigned_results):
            return True
        return self._is_asserted(scope, name)

    def _module_constant(self, node: ast.AST, name: str) -> ast.expr | None:
        module = getattr(node, "_parent", None)
        while module is not None and not isinstance(module, ast.Module):
            module = getattr(module, "_parent", None)
        if module is None:
            return None

        cached = self._module_const_cache.get(id(module))
        if cached is None:
            cached = {}
            for stmt in module.body:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            cached[target.id] = stmt.value
                elif isinstance(stmt, ast.AnnAssign) and isinstance(
                    stmt.target, ast.Name
                ):
                    if stmt.value is not None:
                        cached[stmt.target.id] = stmt.value
            self._module_const_cache[id(module)] = cached
        return cached.get(name)

    def _find_tuple_position(self, targets: list[ast.expr], name: str) -> int | None:
        for target in targets:
            if isinstance(target, ast.Tuple):
                for i, elt in enumerate(target.elts):
                    if isinstance(elt, ast.Name) and elt.id == name:
                        return i
        return None

    def _evaluate_function_call(
        self,
        node: ast.Call,
        *,
        args_allowed: bool = False,
        position: int | None = None,
    ) -> bool:
        match node.func:
            case ast.Attribute(attr=name):
                pass
            case ast.Name(id=name):
                pass
            case _:
                return False

        if name == "SQL":
            return True
        scope = self._find_enclosing_scope(node)
        if isinstance(scope, ast.FunctionDef) and name == scope.name:
            return True

        const_args = self._all_const(node.args, args_allowed=args_allowed)

        if self._root_call is not None:
            self._callsites[name].append((position, const_args, self._root_call))

        if funs := self._function_defs[name]:
            return all(
                self._is_const_def(fun, position=position, const_args=const_args)
                for fun in funs
            )
        return True

    def _is_const_def(
        self,
        node: ast.FunctionDef,
        *,
        position: int | None = None,
        const_args: bool = False,
    ) -> bool:
        cache_key = (id(node), position, const_args)
        if cache_key in self._const_def_cache:
            return self._const_def_cache[cache_key]

        if node.name.startswith("__") or node.name in FUNCTION_WHITELIST:
            self._const_def_cache[cache_key] = True
            return True

        result = all(
            self._is_constexpr(
                ret.value,
                args_allowed=const_args,
                position=position,
            )
            for ret in self._find_return_nodes(node)
            if ret.value is not None
        )
        self._const_def_cache[cache_key] = result
        return result

    def _allowable(self, node: ast.expr) -> bool:
        if self._looks_like_psycopg(node):
            return True

        if self._is_constexpr(node):
            return True

        return (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.attr.startswith("_")
        )

    def _check_attribute_whitelist(self, node: ast.Attribute) -> bool:
        chain = self._get_attribute_chain(node)
        while chain:
            if chain in ATTRIBUTE_WHITELIST or chain.startswith("_"):
                return True
            if "." in chain:
                _, chain = chain.split(".", 1)
            else:
                break
        return False

    @staticmethod
    def _get_attribute_chain(node: ast.expr) -> str:
        match node:
            case ast.Attribute(value=value, attr=attr):
                prefix = SqlInjectionChecker._get_attribute_chain(value)
                return f"{prefix}.{attr}" if prefix else attr
            case ast.Name(id=name):
                return name
            case ast.Call(func=func):
                return SqlInjectionChecker._get_attribute_chain(func)
        return ""

    @staticmethod
    def _get_cursor_name(node: ast.Attribute) -> str:
        parts: list[str] = []
        current = node.value
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        parts.reverse()
        return ".".join(parts)

    @staticmethod
    def _find_enclosing_scope(node: ast.AST) -> ast.AST | None:
        current = getattr(node, "_parent", None)
        while current is not None:
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
                return current
            current = getattr(current, "_parent", None)
        return None

    def _assignments_in(self, scope: ast.AST) -> dict[str, list[ast.AST]]:
        cached = self._assign_cache.get(id(scope))
        if cached is not None:
            return cached

        mapping: dict[str, list[ast.AST]] = defaultdict(list)
        params: set[str] = set()
        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            params = {arg.arg for arg in scope.args.args + scope.args.kwonlyargs}
            if scope.args.vararg:
                params.add(scope.args.vararg.arg)
            if scope.args.kwarg:
                params.add(scope.args.kwarg.arg)
            for name in params:
                mapping[name] = [scope]

        def record(name: str, node: ast.AST) -> None:
            if name not in params:
                mapping[name].append(node)

        for node in ast.walk(scope):
            match node:
                case ast.Assign(targets=targets):
                    for target in targets:
                        if isinstance(target, ast.Name):
                            record(target.id, node)
                        elif isinstance(target, ast.Tuple):
                            for elt in target.elts:
                                if isinstance(elt, ast.Name):
                                    record(elt.id, node)
                case ast.AugAssign(target=ast.Name(id=target_name)):
                    record(target_name, node)
                case ast.For(target=target):
                    if isinstance(target, ast.Name):
                        record(target.id, node)
                    elif isinstance(target, ast.Tuple):
                        for elt in target.elts:
                            if isinstance(elt, ast.Name):
                                record(elt.id, node)
                case ast.comprehension(target=target):
                    if isinstance(target, ast.Name):
                        record(target.id, node)

        self._assign_cache[id(scope)] = mapping
        return mapping

    def _find_assignments(self, scope: ast.AST, name: str) -> Iterator[ast.AST]:
        yield from self._assignments_in(scope).get(name, ())

    @staticmethod
    def _find_return_nodes(node: ast.AST) -> list[ast.Return]:
        return [child for child in ast.walk(node) if isinstance(child, ast.Return)]

    def _is_asserted(self, scope: ast.AST, name: str) -> bool:
        cached = self._assert_cache.get(id(scope))
        if cached is None:
            cached = {
                child.id
                for node in ast.walk(scope)
                if isinstance(node, ast.Assert) and node.test is not None
                for child in ast.walk(node.test)
                if isinstance(child, ast.Name)
            }
            self._assert_cache[id(scope)] = cached
        return name in cached

    @staticmethod
    def _looks_like_psycopg(node: ast.expr) -> bool:
        match node:
            case ast.Call(func=ast.Attribute(attr="format", value=value)):
                return SqlInjectionChecker._looks_like_psycopg(value)
            case ast.Call(func=ast.Attribute(value=ast.Name(id=name))):
                return name in ("sql", "psycopg2", "psycopg")
            case ast.Call(func=ast.Name(id="SQL")):
                return True
            case ast.Name(id=name):
                return name == "SQL"
        return False
