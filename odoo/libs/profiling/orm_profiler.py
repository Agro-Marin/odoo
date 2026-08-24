import itertools
import logging
import os
import time

_logger = logging.getLogger("odoo.orm.profile")

_orm_profiling_enabled: bool = os.environ.get("ODOO_ORM_PROFILE", "").lower() in (
    "1",
    "true",
    "yes",
)

if _orm_profiling_enabled:
    _logger.info("ORM aggregate profiling enabled (ODOO_ORM_PROFILE=1)")


class _OrmProfile:
    """A phase timer for one ORM operation, and the emission of its line.

    ``_marks`` is insertion-ordered, so the phases *are* its consecutive pairs
    and each one is named by the mark that ends it. :meth:`report` derives the
    whole ``| acl=0.1 prep=0.2 ...`` tail from that.

    It did not, until 2026-08-24. Twenty-six call sites each carried the same
    ``prof.stop()`` / ``if prof.debug: logger.debug(...)`` block with a
    hand-written format string listing one ``prof.ms(a, b)`` per phase --
    about 150 lines of it, and every one an opportunity to name a phase in the
    format string that the marks do not have. ``write()`` had already taken
    it: its last phase was marked ``validate1`` and labelled ``inverse=``, so
    the line said ``validate=`` over the time spent validating and ``inverse=``
    over something else entirely.
    """

    __slots__ = ("_final", "_marks", "agg", "debug")

    def __init__(self, logger: logging.Logger) -> None:
        self.debug = logger.isEnabledFor(logging.DEBUG)
        self.agg = _orm_profiling_enabled
        self._marks: dict[str, float] = {}
        self._final = "end"
        if self.debug or self.agg:
            self._marks["start"] = time.perf_counter()

    def mark(self, name: str) -> None:
        if self.debug:
            self._marks[name] = time.perf_counter()

    def stop(self, final: str = "end") -> None:
        """Close the last phase, naming it.

        The name goes here rather than to :meth:`report` because it belongs to
        the phase, which ends at this call and not at the emission.
        """
        if self.debug or self.agg:
            self._final = final
            self._marks[final] = time.perf_counter()

    def ms(self, start: str, end: str) -> float:
        return (self._marks[end] - self._marks[start]) * 1000.0

    @property
    def elapsed(self) -> float:
        return self._marks[self._final] - self._marks["start"]

    def report(self, logger: logging.Logger, message: str, *args: object) -> None:
        """Emit ``[<ms>] <message> | <phase>=<ms> ...``, phases and all.

        A no-op below DEBUG, so a caller writes it unconditionally. The phase
        tail is not passed in because it is already here: `message` describes
        the operation, the marks describe its shape.
        """
        if not self.debug:
            return
        times = list(self._marks.values())
        if len(times) > 2:
            names = list(self._marks)[1:]
            phases = " | " + " ".join(f"{name}=%.1f" for name in names)
            args = (
                *args,
                *((b - a) * 1000.0 for a, b in itertools.pairwise(times)),
            )
        else:
            phases = ""
        # Assembled into a name first: the linter reads a `+` in the call
        # itself as string-building the logger should have been left to do,
        # and here it is the *format* being built, above a `debug` guard that
        # has already returned when logging is off.
        fmt = "[%.3f ms] " + message + phases
        logger.debug(fmt, self.elapsed * 1000.0, *args)


class _OpStats:
    __slots__ = ("count", "records", "time")

    def __init__(self) -> None:
        self.count: int = 0
        self.records: int = 0
        self.time: float = 0.0


type _Key = tuple[str, str]


class OrmProfiler:
    __slots__ = ("_data", "_total_time")

    def __init__(self) -> None:
        self._data: dict[_Key, _OpStats] = {}
        self._total_time: float = 0.0

    def _record(
        self,
        operation: str,
        model_name: str,
        record_count: int,
        elapsed: float,
    ) -> None:
        key: _Key = (operation, model_name)
        stats = self._data.get(key)
        if stats is None:
            stats = _OpStats()
            self._data[key] = stats
        stats.count += 1
        stats.records += record_count
        stats.time += elapsed
        self._total_time += elapsed

    def record(
        self,
        operation: str,
        model_name: str,
        record_count: int,
        elapsed: float,
    ) -> None:
        """Was eight methods, one per operation, each a single call to
        :meth:`_record` with its own name spelled twice: in the method name and
        in the string it passed. The operation is data, so it travels as an
        argument."""
        self._record(operation, model_name, record_count, elapsed)

    def report(self) -> None:
        if not self._data or not _logger.isEnabledFor(logging.WARNING):
            return

        sorted_entries = sorted(
            self._data.items(),
            key=lambda item: item[1].time,
            reverse=True,
        )

        op_totals: dict[str, _OpStats] = {}
        for (operation, _model), stats in self._data.items():
            agg = op_totals.get(operation)
            if agg is None:
                agg = _OpStats()
                op_totals[operation] = agg
            agg.count += stats.count
            agg.records += stats.records
            agg.time += stats.time

        lines = [
            (
                f"ORM Profile Summary ({len(self._data)} model/op pairs, "
                f"{self._total_time * 1000:.1f} ms total):"
            )
        ]

        lines.append("  Operation totals:")
        for op, agg in sorted(op_totals.items(), key=lambda x: x[1].time, reverse=True):
            lines.append(
                f"    {op:>10s}: {agg.count:4d} calls, "
                f"{agg.records:6d} records, {agg.time * 1000:8.1f} ms"
            )

        shown = sorted_entries[:20]
        if len(sorted_entries) > len(shown):
            lines.append(
                f"  Top hotspots by time (showing {len(shown)} of "
                f"{len(sorted_entries)}):"
            )
        else:
            lines.append("  Top hotspots by time:")
        for (operation, model_name), stats in shown:
            pct = (stats.time / self._total_time * 100) if self._total_time else 0
            lines.append(
                f"    {operation:>10s} {model_name}: "
                f"{stats.count:4d} calls, {stats.records:6d} records, "
                f"{stats.time * 1000:8.1f} ms ({pct:4.1f}%)"
            )

        _logger.warning("\n".join(lines))

    def clear(self) -> None:
        self._data.clear()
        self._total_time = 0.0
