"""`.company_id` read off an `account.tax` recordset.

`account.tax` carries a many2many `company_ids` in this fork, not a singular
`company_id`; the attribute does not exist and the read is an `AttributeError`
at runtime. It survives review because the expression reads like every other
company check, and it survives testing because the `filtered` lambda only runs
when the recordset is non-empty -- a product with no taxes exercises the line
and proves nothing.

Thirteen of these were live across two repositories when the rule was written,
one of them making every subcontracted-service purchase order fail to generate.

The shape caught is a `filtered()` over a tax-typed field whose lambda reads
`.company_id` off its own parameter. That is where the ones found actually
lived; a general "is this expression an account.tax" question is not one a
static pass can answer.
"""

import ast
from collections.abc import Iterator
from dataclasses import dataclass

#: Fields whose comodel is `account.tax`.
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
