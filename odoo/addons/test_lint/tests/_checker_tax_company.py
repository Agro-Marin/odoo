import ast
from collections.abc import Iterator
from dataclasses import dataclass

TAX_FIELDS = frozenset(
    {
        "tax_id",
        "tax_ids",
        "taxes_id",
        "supplier_taxes_id",
        "original_tax_ids",
        "l10n_tax_ids",
    }
)


@dataclass
class Violation:
    lineno: int
    col_offset: int
    message: str = (
        "account.tax has company_ids (many2many), not company_id: reading it "
        "raises AttributeError. Use "
        "`filtered_domain(env['account.tax']._check_company_domain(company))`, "
        "or `tax.company_ids & company.parent_ids` inside a compound lambda."
    )


def _reads_company_id(lambda_node: ast.Lambda, name: str) -> Iterator[ast.Attribute]:
    for node in ast.walk(lambda_node.body):
        match node:
            case ast.Attribute(attr="company_id", value=ast.Name(id=target)) if (
                target == name
            ):
                yield node


DIVERGED_MODELS = frozenset(
    {
        "account.tax",
        "account.tax.group",
        "account.tax.repartition.line",
        "account.account",
    }
)

DOMAIN_METHODS = frozenset(
    {
        "search",
        "search_count",
        "search_fetch",
        "_search",
        "read_group",
        "_read_group",
        "filtered_domain",
    }
)

DOMAIN_MESSAGE = (
    "account.tax and account.account carry company_ids (many2many), not "
    "company_id: a ('company_id', ...) domain leaf against them matches nothing "
    "and raises. Use `filtered_domain(env['account.tax']._check_company_domain(company))`."
)


def _get_model_aliases(tree: ast.Module) -> dict[str, frozenset[str]]:
    aliases: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        match node:
            case ast.For(target=ast.Name(id=name), iter=ast.Tuple() | ast.List() as it):
                names = {
                    e.value
                    for e in it.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                }
                if names:
                    aliases.setdefault(name, set()).update(names)
    return {k: frozenset(v) for k, v in aliases.items()}


def _get_env_models(
    node: ast.AST, aliases: dict[str, frozenset[str]]
) -> frozenset[str]:
    while True:
        match node:
            case ast.Subscript(value=ast.Attribute(attr="env"), slice=key):
                match key:
                    case ast.Constant(value=str() as name):
                        return frozenset({name})
                    case ast.Name(id=alias):
                        return aliases.get(alias, frozenset())
                return frozenset()
            case ast.Call(func=inner) | ast.Attribute(value=inner):
                node = inner
            case _:
                return frozenset()


def _get_company_id_leaves(node: ast.AST) -> Iterator[ast.AST]:
    for child in ast.walk(node):
        match child:
            case (
                ast.Tuple(elts=[ast.Constant(value="company_id"), *_])
                | ast.List(elts=[ast.Constant(value="company_id"), *_])
            ):
                yield child


def check(tree: ast.Module, nodes=None) -> Iterator[Violation]:
    aliases = _get_model_aliases(tree)
    for node in nodes if nodes is not None else ast.walk(tree):
        match node:
            case ast.Call(
                func=ast.Attribute(attr="filtered", value=ast.Attribute(attr=field)),
                args=[ast.Lambda(args=ast.arguments(args=[first, *_])) as lam, *_],
            ) if field in TAX_FIELDS:
                for read in _reads_company_id(lam, first.arg):
                    yield Violation(read.lineno, read.col_offset)
            case ast.Call(func=ast.Attribute(attr=method, value=receiver)) if (
                method in DOMAIN_METHODS
                and _get_env_models(receiver, aliases) & DIVERGED_MODELS
            ):
                for arg in [*node.args, *(kw.value for kw in node.keywords)]:
                    for leaf in _get_company_id_leaves(arg):
                        yield Violation(leaf.lineno, leaf.col_offset, DOMAIN_MESSAGE)
