import logging
import os
import sys
import types
from pathlib import Path

__all__ = [
    "NplusOneTracker",
]


_logger = logging.getLogger("odoo.orm.nplusone")

_n1_enabled: bool = os.environ.get("ODOO_NPLUSONE", "").lower() in (
    "1",
    "true",
    "yes",
)

if _n1_enabled:
    _logger.info("N+1 CRUD detection enabled (ODOO_NPLUSONE=1)")

_ODOO_DIR = Path(__file__).resolve().parents[2]
_ORM_PREFIX: str = str(_ODOO_DIR / "orm") + os.sep

_SKIP_PREFIXES: tuple[str, ...] = (
    _ORM_PREFIX,
    str(_ODOO_DIR / "api") + os.sep,
)


class _NplusOneEntry:
    __slots__ = ("count", "total_records", "vals_fingerprints")

    def __init__(self) -> None:
        self.count: int = 0
        self.total_records: int = 0
        self.vals_fingerprints: set[frozenset[str]] = set()


type _Key = tuple[str, str, str, int]

READ_OPERATIONS: frozenset[str] = frozenset(("search", "fetch", "read"))
"""Operations judged by records-per-call rather than by call count alone.

A write repeated from one line is an N+1 whatever it writes. A *read* repeated
from one line is only an N+1 if each call brings back almost nothing -- a loop
that searches a wide result set every time is doing something else, and flagging
it would train people to ignore the report.
"""


class NplusOneTracker:
    __slots__ = ("_data",)

    THRESHOLD = 3

    READ_THRESHOLD = 8
    """How many repeats of a read from one line before it is worth a line."""

    READ_RECORDS_PER_CALL = 2.0
    """Above this average, a repeated read is a loop over data, not an N+1."""

    def __init__(self) -> None:
        self._data: dict[_Key, _NplusOneEntry] = {}

    def record(
        self,
        operation: str,
        model_name: str,
        record_count: int,
        field_fingerprint: frozenset[str],
    ) -> None:
        try:
            frame: types.FrameType | None = sys._getframe(2)
        except ValueError:
            return
        while frame is not None:
            code = frame.f_code
            if (
                not code.co_filename.startswith(_SKIP_PREFIXES)
                and code.co_name != operation
            ):
                break
            frame = frame.f_back

        if frame is None:
            return

        key: _Key = (
            operation,
            model_name,
            frame.f_code.co_filename,
            frame.f_lineno,
        )

        entry = self._data.get(key)
        if entry is None:
            entry = _NplusOneEntry()
            self._data[key] = entry

        entry.count += 1
        entry.total_records += record_count
        entry.vals_fingerprints.add(field_fingerprint)

    def report(self) -> None:
        if not _logger.isEnabledFor(logging.WARNING):
            return

        violations: list[tuple[_Key, _NplusOneEntry]] = [
            (key, entry)
            for key, entry in self._data.items()
            if self._is_violation(key[0], entry)
        ]
        if not violations:
            return

        lines = [f"N+1 CRUD detected ({len(violations)} call site(s)):"]
        for (operation, model_name, filename, lineno), entry in violations:
            if operation in READ_OPERATIONS:
                per_call = entry.total_records / entry.count
                hint = f" [{per_call:.1f} records per call — batch the ids]"
            elif len(entry.vals_fingerprints) == 1:
                hint = " [same fields every call — easily batchable]"
            elif len(entry.vals_fingerprints) <= 3:
                hint = f" [{len(entry.vals_fingerprints)} distinct field sets]"
            else:
                hint = ""
            lines.append(
                f"  {operation}() on {model_name}: "
                f"{entry.count} calls, {entry.total_records} records total"
                f" @ {filename}:{lineno}{hint}"
            )
        _logger.warning("\n".join(lines))

    def _is_violation(self, operation: str, entry: _NplusOneEntry) -> bool:
        if operation not in READ_OPERATIONS:
            return entry.count >= self.THRESHOLD
        return (
            entry.count >= self.READ_THRESHOLD
            and entry.total_records <= entry.count * self.READ_RECORDS_PER_CALL
        )

    def clear(self) -> None:
        self._data.clear()
