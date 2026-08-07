import logging
import os
import sys
import types
from pathlib import Path

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


class NplusOneTracker:
    __slots__ = ("_data",)

    THRESHOLD = 3

    def __init__(self) -> None:
        self._data: dict[_Key, _NplusOneEntry] = {}

    def record(
        self,
        operation: str,
        model_name: str,
        record_count: int,
        field_fingerprint: frozenset[str],
    ) -> None:
        frame: types.FrameType | None = sys._getframe(2)
        while frame is not None:
            code = frame.f_code
            if (
                not any(code.co_filename.startswith(p) for p in _SKIP_PREFIXES)
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
            if entry.count >= self.THRESHOLD
        ]
        if not violations:
            return

        lines = [f"N+1 CRUD detected ({len(violations)} call site(s)):"]
        for (operation, model_name, filename, lineno), entry in violations:
            if len(entry.vals_fingerprints) == 1:
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

    def clear(self) -> None:
        self._data.clear()
