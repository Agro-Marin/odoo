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


def check(tree: ast.Module, nodes=None) -> Iterator[Violation]:
    for node in nodes if nodes is not None else ast.walk(tree):
        match node:
            case ast.Call(
                func=ast.Attribute(attr="filtered", value=ast.Attribute(attr=field)),
                args=[ast.Lambda(args=ast.arguments(args=[first, *_])) as lam, *_],
            ) if field in TAX_FIELDS:
                for read in _reads_company_id(lam, first.arg):
                    yield Violation(read.lineno, read.col_offset)
