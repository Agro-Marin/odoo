"""SQL string utilities.

Pure Python SQL helpers with no Odoo dependencies.
"""

__all__ = [
    "escape_psql",
    "make_identifier",
    "make_index_name",
    "pg_varchar",
    "reverse_order",
]

from binascii import crc32


def escape_psql(to_escape: str) -> str:
    r"""Escape special characters for PostgreSQL LIKE patterns.

    Escapes backslash, percent, and underscore characters which have
    special meaning in LIKE patterns.

    :param to_escape: The string to escape
    :returns: The escaped string

    Example::

        >>> escape_psql('10%_off')
        '10\\%\\_off'
    """
    return to_escape.replace("\\", r"\\").replace("%", r"\%").replace("_", r"\_")


def pg_varchar(size: int = 0) -> str:
    """Return the VARCHAR declaration for the provided size.

    :param size: VARCHAR size (0 or negative for unlimited)
    :returns: 'VARCHAR(n)' for positive size, 'VARCHAR' otherwise
    :raises ValueError: If size is not an integer

    Example::

        >>> pg_varchar(255)
        'VARCHAR(255)'
        >>> pg_varchar()
        'VARCHAR'
        >>> pg_varchar(0)
        'VARCHAR'
    """
    if size:
        if not isinstance(size, int):
            raise ValueError(f"VARCHAR parameter should be an int, got {type(size)}")
        if size > 0:
            return f"VARCHAR({size})"
    return "VARCHAR"


def _split_order_items(order: str) -> list[str]:
    """Split an ORDER BY clause on its top-level commas only.

    A naive ``order.split(",")`` breaks expressions with argument lists
    (``coalesce(a, b) desc``) or commas inside quoted identifiers
    (``"a,b"``). This splits on commas that are outside parentheses and
    outside a double-quoted identifier.
    """
    items: list[str] = []
    depth = 0
    in_quote = False
    start = 0
    for i, ch in enumerate(order):
        if ch == '"':
            in_quote = not in_quote
        elif in_quote:
            continue
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            items.append(order[start:i])
            start = i + 1
    items.append(order[start:])
    return items


def reverse_order(order: str) -> str:
    """Reverse an ORDER BY clause.

    Flips ``ASC`` <-> ``DESC`` for each column and, where an explicit null
    placement is given, ``NULLS FIRST`` <-> ``NULLS LAST`` -- reversing an
    ordering must reverse where the NULLs land too, so the reversed clause
    yields the exact reverse row sequence (e.g. for a "last record" query).

    Column expressions are preserved verbatim: quoting and case are kept
    (``"Name"`` stays ``"Name"``). Empty items (a trailing or doubled comma)
    are skipped.

    :param order: An ORDER BY clause (without the 'ORDER BY' keywords)
    :returns: The reversed order clause

    Example::

        >>> reverse_order('name asc, date desc')
        'name desc, date asc'
        >>> reverse_order('id')
        'id desc'
        >>> reverse_order('name desc nulls last')
        'name asc nulls first'
        >>> reverse_order('"Name" asc')
        '"Name" desc'
        >>> reverse_order('coalesce(a, b) desc, name asc')
        'coalesce(a, b) asc, name desc'
    """
    items = []
    for item in _split_order_items(order):
        tokens = item.split()
        if not tokens:
            continue

        nulls = ""
        if len(tokens) >= 3 and tokens[-2].lower() == "nulls":
            nulls = " nulls first" if tokens[-1].lower() == "last" else " nulls last"
            tokens = tokens[:-2]

        direction = "asc" if tokens[-1].lower() == "desc" else "desc"
        if tokens[-1].lower() in ("asc", "desc"):
            tokens = tokens[:-1]
        if not tokens:
            continue
        items.append(f"{' '.join(tokens)} {direction}{nulls}")
    return ", ".join(items)


def make_identifier(identifier: str) -> str:
    """Return identifier, possibly modified to fit PostgreSQL's limit.

    PostgreSQL identifiers are limited to 63 characters. If the identifier
    is too long, it's truncated and padded with a CRC32 hash to maintain
    uniqueness.

    :param identifier: The identifier to process
    :returns: The (possibly truncated) identifier

    Example::

        >>> make_identifier('short_name')
        'short_name'
        >>> len(make_identifier('a' * 100))
        63
    """
    encoded = identifier.encode()
    if len(encoded) > 63:
        prefix = encoded[:54].decode(errors="ignore")
        return f"{prefix}_{crc32(encoded):08x}"
    return identifier


def make_index_name(table_name: str, column_name: str) -> str:
    """Return an index name according to PostgreSQL conventions.

    :param table_name: The table name
    :param column_name: The column name
    :returns: An index name in the format '{table}__{column}_index'

    Example::

        >>> make_index_name('res_partner', 'email')
        'res_partner__email_index'
    """
    return make_identifier(f"{table_name}__{column_name}_index")
