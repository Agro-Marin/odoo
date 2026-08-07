__all__ = [
    "escape_psql",
    "make_identifier",
    "make_index_name",
    "pg_varchar",
    "reverse_order",
]

from binascii import crc32


def escape_psql(to_escape: str) -> str:
    return to_escape.replace("\\", r"\\").replace("%", r"\%").replace("_", r"\_")


def pg_varchar(size: int = 0) -> str:
    if size:
        if not isinstance(size, int):
            raise ValueError(f"VARCHAR parameter should be an int, got {type(size)}")
        if size > 0:
            return f"VARCHAR({size})"
    return "VARCHAR"


def _split_order_items(order: str) -> list[str]:
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
    encoded = identifier.encode()
    if len(encoded) > 63:
        prefix = encoded[:54].decode(errors="ignore")
        return f"{prefix}_{crc32(encoded):08x}"
    return identifier


def make_index_name(table_name: str, column_name: str) -> str:
    return make_identifier(f"{table_name}__{column_name}_index")
