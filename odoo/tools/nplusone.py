"""
N+1 CRUD detection for Odoo ORM.

Detects repeated single-record create/write/unlink calls from the same call
site within a transaction — a pattern that is 5-15x slower than batching.

Activation: set ``ODOO_NPLUSONE=1`` in the environment (dev-only, opt-in). The
flag is read once at import (mirroring ``ODOO_ORM_PROFILE`` in
:mod:`odoo.tools.orm_profiler`): consumers freeze it via
``from odoo.tools.nplusone import _n1_enabled``, so a rebind after those imports
would not reach their copies — activation must be settled at import time, not by
a later ``setup()`` call.

When disabled, overhead is a single boolean check per CRUD call
(``_n1_enabled``). Violations above the threshold are reported via the
``odoo.orm.nplusone`` logger at ``Transaction.flush()``.
"""

import logging
import os
import sys
from pathlib import Path

_logger = logging.getLogger("odoo.orm.nplusone")

# Module-level fast flag: one LOAD_GLOBAL + branch per CRUD call when off.
# Read from the environment at import (see module docstring): consumers freeze
# this value with ``from ... import _n1_enabled``, so it must be correct now.
_n1_enabled: bool = os.environ.get("ODOO_NPLUSONE", "").lower() in (
    "1",
    "true",
    "yes",
)

if _n1_enabled:
    _logger.info("N+1 CRUD detection enabled (ODOO_NPLUSONE=1)")

# Frames under these prefixes are framework-internal and skipped when finding
# the external caller: odoo/orm/ and odoo/api/.
_ODOO_DIR = Path(__file__).resolve().parent.parent
_ORM_PREFIX: str = str(_ODOO_DIR / "orm") + "/"

_SKIP_PREFIXES: tuple[str, ...] = (
    _ORM_PREFIX,
    str(_ODOO_DIR / "api") + "/",
)


class _NplusOneEntry:
    """Accumulator for a single (operation, model, file, line) call site."""

    __slots__ = ("count", "total_records", "vals_fingerprints")

    def __init__(self) -> None:
        self.count: int = 0
        self.total_records: int = 0
        self.vals_fingerprints: set[frozenset[str]] = set()


# Key: (operation, model_name, filename, lineno)
type _Key = tuple[str, str, str, int]


class NplusOneTracker:
    """Collects N+1 CRUD call patterns within a single transaction."""

    __slots__ = ("_data",)

    THRESHOLD = 3  # minimum calls from same site to trigger a warning

    def __init__(self) -> None:
        self._data: dict[_Key, _NplusOneEntry] = {}

    def record(
        self,
        operation: str,
        model_name: str,
        record_count: int,
        field_fingerprint: frozenset[str],
    ) -> None:
        """Record a CRUD call from the create/write/unlink ORM mixins."""
        # Walk the stack to find the first frame that is the *real* external
        # caller. Skip two kinds of frames:
        #   1. ORM/api internals (by file prefix), and
        #   2. the create/write/unlink super()-delegation chain -- frames whose
        #      function name is the tracked operation. Most models override
        #      create/write/unlink and end in ``super().create(...)``; without
        #      this the walk would stop at that override line and blame the model
        #      plumbing instead of the loop that issued the repeated single-record
        #      calls.
        frame = sys._getframe(2)  # skip record() + the CRUD method itself
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
        """Emit warnings for call sites that reach the threshold."""
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
