"""Sampling profiler for Odoo — flamegraphs, SQL tracing, memory tracking."""

import json
import logging
import re
import sys
import threading
import time
import tracemalloc
from contextlib import ExitStack, nullcontext
from datetime import datetime
from typing import TYPE_CHECKING, Any

from psycopg import OperationalError

from odoo import tools
from odoo.libs.gc import disabling_gc
from odoo.tools import SQL

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import FrameType

_logger = logging.getLogger(__name__)

# Non-patched time functions, so profiling is unaffected by freezegun.
real_datetime_now = datetime.now
real_time = time.time.__call__
real_cpu_time = time.thread_time.__call__


def _format_frame(frame: FrameType) -> tuple[str, int, str, str]:
    """Format a stack frame as (filename, lineno, name, line)."""
    code = frame.f_code
    return (code.co_filename, frame.f_lineno, code.co_name, "")


def _format_stack(stack: list[tuple[str, int, str, str]]) -> list[list[Any]]:
    """Format a list of frame tuples as lists (for JSON serialisation)."""
    return [list(frame) for frame in stack]


def get_current_frame(thread: threading.Thread | None = None) -> FrameType:
    """Return the current frame, skipping frames inside this profiler module."""
    if thread:
        frame = sys._current_frames()[thread.ident]
    else:
        frame = sys._getframe()
    while frame.f_code.co_filename == __file__:
        frame = frame.f_back
    return frame


def _get_stack_trace(
    frame: FrameType | None,
    limit_frame: FrameType | None = None,
) -> list[tuple[str, int, str, str]]:
    """Return the stack trace from ``frame`` up to (but excluding) ``limit_frame``."""
    stack = []
    while frame is not None and frame != limit_frame:
        stack.append(_format_frame(frame))
        frame = frame.f_back
    if frame is None and limit_frame:
        _logger.runbot("Limit frame was not found")
    return list(reversed(stack))


def stack_size() -> int:
    """Return the current call-stack depth."""
    frame = get_current_frame()
    size = 0
    while frame:
        size += 1
        frame = frame.f_back
    return size


def make_session(name: str = "") -> str:
    """Return a session string with the current timestamp and optional name."""
    return f"{real_datetime_now():%Y-%m-%d %H:%M:%S} {name}"


def force_hook() -> None:
    """Force periodic collectors to take a stack trace now.

    Useful before long calls that do not release the GIL, so their time is
    attributed to the right stack trace instead of some arbitrary former frame.
    """
    thread = threading.current_thread()
    for func in getattr(thread, "profile_hooks", ()):
        func()


class Collector:
    """Base class for profiling-data collectors.

    A collector gathers entries for a profiler — usually stack traces with
    timing and the ExecutionContext of the current thread. Subclassed; provides
    the default entry-creation behavior.
    """

    name = None  # symbolic name of the collector
    _store = (
        None  # storage discriminator; the "others" collector sets it (see line ~760)
    )
    _registry = {}  # map collector names to their class

    @classmethod
    def __init_subclass__(cls):
        if cls.name:
            cls._registry[cls.name] = cls
            cls._registry[cls.__name__] = cls

    @classmethod
    def make(cls, name: str, *args: Any, **kwargs: Any) -> Collector:
        """Instantiate a collector corresponding to the given name."""
        return cls._registry[name](*args, **kwargs)

    def __init__(self) -> None:
        self._processed: bool = False
        self._entries: list[dict[str, Any]] = []
        self.profiler: Profiler | None = None

    def start(self) -> None:
        """Start the collector."""

    def stop(self) -> None:
        """Stop the collector."""

    def add(
        self,
        entry: dict[str, Any] | None = None,
        frame: FrameType | None = None,
    ) -> None:
        """Add an entry (dict) to this collector."""
        self._entries.append(
            {
                "stack": self._get_stack_trace(frame),
                "exec_context": getattr(self.profiler.init_thread, "exec_context", ()),
                "start": real_time(),
                **(entry or {}),
            }
        )

    def progress(
        self,
        entry: dict[str, Any] | None = None,
        frame: FrameType | None = None,
    ) -> None:
        """Add an entry, or end the profiler if the entry-count limit is reached."""
        if (
            self.profiler.entry_count_limit
            and self.profiler.counter >= self.profiler.entry_count_limit
        ):
            self.profiler.end()
            return
        self.profiler.counter += 1
        self.add(entry=entry, frame=frame)

    def _get_stack_trace(
        self, frame: FrameType | None = None
    ) -> list[tuple[str, int, str, str]] | None:
        """Return the stack trace to be included in a given entry."""
        frame = frame or get_current_frame(self.profiler.init_thread)
        return _get_stack_trace(frame, self.profiler.init_frame)

    def post_process(self) -> None:
        """Post-process collected entries by resolving file line text."""
        for entry in self._entries:
            stack = entry.get("stack", [])
            self.profiler._add_file_lines(stack)

    @property
    def entries(self) -> list[dict[str, Any]]:
        """Return the entries of the collector after postprocessing."""
        if not self._processed:
            self.post_process()
            self.processed_entries = self._entries
            self._entries = None  # avoid modification after processing
            self._processed = True
        return self.processed_entries

    def summary(self) -> str:
        """Return a brief text summary of this collector's data."""
        # After ``entries`` runs post-processing it nulls ``_entries`` and moves
        # the data to ``processed_entries``; read the live source so a call after
        # processing (e.g. Profiler(log=True).end()) does not crash on len(None).
        entries = self.processed_entries if self._processed else self._entries
        return f"{'=' * 10} {self.name} {'=' * 10} \n Entries: {len(entries)}"


class SQLCollector(Collector):
    """Saves all executed queries in the current thread with the call stack."""

    name = "sql"

    def start(self) -> None:
        """Register the SQL query hook on the profiler thread."""
        init_thread = self.profiler.init_thread
        if not hasattr(init_thread, "query_hooks"):
            init_thread.query_hooks = []
        init_thread.query_hooks.append(self.hook)

    def stop(self) -> None:
        """Unregister the SQL query hook."""
        self.profiler.init_thread.query_hooks.remove(self.hook)

    def hook(
        self,
        cr: Any,
        query: Any,
        params: Any,
        query_start: float,
        query_time: float,
    ) -> None:
        """Called for each executed SQL query."""
        self.progress(
            {
                "query": str(query),
                "full_query": str(cr._format(query, params)),
                "start": query_start,
                "time": query_time,
            }
        )

    def summary(self) -> str:
        total_time = sum(entry["time"] for entry in self._entries) or 1
        sql_entries = ""
        for entry in self._entries:
            sql_entries += f"\n{'-' * 100}'\n'{entry['time']}  {'*' * int(entry['time'] / total_time * 100)}'\n'{entry['full_query']}"
        return super().summary() + sql_entries


class _BasePeriodicCollector(Collector):
    """Record execution frames asynchronously at most every ``interval`` seconds.

    :param interval: time to wait in seconds between two samples.
    """

    _min_interval: float = 0.001
    _max_interval: float = 5
    _default_interval: float = 0.001

    def __init__(self, interval: float | None = None) -> None:
        super().__init__()
        self.active: bool = False
        self.frame_interval: float = interval or self._default_interval
        self.__thread = threading.Thread(target=self.run)
        self.last_frame: FrameType | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Start the periodic sampling thread."""
        interval = self.profiler.params.get(f"{self.name}_interval")
        if interval:
            self.frame_interval = min(
                max(float(interval), self._min_interval), self._max_interval
            )
        init_thread = self.profiler.init_thread
        if not hasattr(init_thread, "profile_hooks"):
            init_thread.profile_hooks = []
        init_thread.profile_hooks.append(self.progress)
        self.__thread.start()

    def run(self) -> None:
        """Sampling loop run in the background thread."""
        self.active = True
        # ``_last_time`` (not ``last_time``): ``add()`` reads ``self._last_time``.
        self._last_time = real_time()
        while self.active:  # maybe add a check on parent_thread state?
            self.progress()
            self._stop_event.wait(self.frame_interval)

    def stop(self) -> None:
        self.active = False
        self._stop_event.set()
        self._entries.append({"stack": [], "start": real_time()})  # final end frame
        if self.__thread.is_alive() and self.__thread is not threading.current_thread():
            self.__thread.join()
        self.profiler.init_thread.profile_hooks.remove(self.progress)


class PeriodicCollector(_BasePeriodicCollector):
    name = "traces_async"

    def add(self, entry=None, frame=None):
        """Add an entry (dict) to this collector."""
        if self.last_frame:
            duration = real_time() - self._last_time
            if duration > self.frame_interval * 10 and self.last_frame:
                # Slept >10 intervals, typically a C call that didn't release
                # the GIL: the call falls between two frames and is wrongly
                # attributed to the last one. Flag it explicitly.
                self._entries[-1]["stack"].append(
                    (
                        "profiling",
                        0,
                        "⚠ Profiler freezed for %s s" % duration,
                        "",
                    )
                )
            self.last_frame = None  # skip duplicate detection on the next frame
        self._last_time = real_time()

        frame = frame or get_current_frame(self.profiler.init_thread)
        if frame == self.last_frame:
            # Don't save an identical consecutive frame.
            return
        self.last_frame = frame
        super().add(entry=entry, frame=frame)


_lock = threading.Lock()


class MemoryCollector(_BasePeriodicCollector):
    name = "memory"
    _store = "others"
    _min_interval = 0.01
    _default_interval = 1

    def start(self):
        _lock.acquire()
        tracemalloc.start()
        super().start()

    def add(self, entry=None, frame=None):
        """Add an entry (dict) to this collector."""
        self._entries.append(
            {
                "start": real_time(),
                "memory": tracemalloc.take_snapshot(),
            }
        )

    def stop(self):
        super().stop()
        _lock.release()
        tracemalloc.stop()

    def post_process(self):
        for i, entry in enumerate(self._entries):
            if entry.get("memory", False):
                entry_statistics = entry["memory"].statistics("traceback")
                modified_entry_statistics = [
                    {
                        "traceback": list(statistic.traceback._frames),
                        "size": statistic.size,
                    }
                    for statistic in entry_statistics
                ]
                self._entries[i] = {
                    "memory_tracebacks": modified_entry_statistics,
                    "start": entry["start"],
                }


class SyncCollector(Collector):
    """Record complete execution synchronously.

    Note: ``--limit-memory-hard`` may need to be increased when launching Odoo.
    """

    name = "traces_sync"

    def start(self):
        if sys.gettrace() is not None:
            _logger.error(
                "Cannot start SyncCollector, settrace already set: %s",
                sys.gettrace(),
            )
        assert not self._processed, (
            "You cannot start SyncCollector after accessing entries."
        )
        sys.settrace(self.hook)  # todo test setprofile, but maybe not multithread safe

    def stop(self):
        sys.settrace(None)

    def hook(self, _frame, event, _arg=None):
        if event == "line":
            return None
        entry = {"event": event, "frame": _format_frame(_frame)}
        if event == "call" and _frame.f_back:
            # Parent frame gives the line number of the call.
            entry["parent_frame"] = _format_frame(_frame.f_back)
        self.progress(entry, frame=_frame)
        return self.hook

    def _get_stack_trace(self, frame=None):
        # Full stack traces are slow and unneeded here: SyncCollector saves only
        # the top frame and event per call, rebuilding the full stack at the end.
        return None

    def post_process(self):
        # Rebuild full stack traces from the evented traces. Speedscope would
        # re-event these anyway, but reconstructing here is simpler to integrate
        # with the speedscope logic, especially when mixed with SQLCollector.
        stack = []
        for entry in self._entries:
            frame = entry.pop("frame")
            event = entry.pop("event")
            if event == "call":
                if stack:
                    stack[-1] = entry.pop("parent_frame")
                stack.append(frame)
            elif event == "return":
                stack.pop()
            entry["stack"] = stack[:]
        super().post_process()


class QwebTracker:
    """Tracks QWeb directive rendering for the QwebCollector."""

    def __init__(self, view_id: int, arch: Any, cr: Any) -> None:
        current_thread = (
            threading.current_thread()
        )  # don't store current_thread on self
        self.execution_context_enabled: bool | None = getattr(
            current_thread, "profiler_params", {}
        ).get("execution_context_qweb")
        self.qweb_hooks: tuple[Callable[..., None], ...] = getattr(
            current_thread, "qweb_hooks", ()
        )
        self.context_stack: list[ExecutionContext] = []
        self.cr: Any = cr
        self.view_id: int = view_id
        for hook in self.qweb_hooks:
            hook("render", self.cr.sql_log_count, view_id=view_id, arch=arch)

    def enter_directive(
        self, directive: str, attrib: dict[str, str], xpath: str
    ) -> None:
        execution_context = None
        if self.execution_context_enabled:
            directive_info = {}
            if ("t-" + directive) in attrib:
                directive_info["t-" + directive] = repr(attrib["t-" + directive])
            if directive == "set":
                if "t-value" in attrib:
                    directive_info["t-value"] = repr(attrib["t-value"])
                if "t-valuef" in attrib:
                    directive_info["t-valuef"] = repr(attrib["t-valuef"])

                for key, value in attrib.items():
                    if key.startswith(("t-set-", "t-setf-")):
                        directive_info[key] = repr(value)
            elif directive == "foreach":
                directive_info["t-as"] = repr(attrib["t-as"])
            elif (
                directive == "groups"
                and "groups" in attrib
                and not directive_info.get("t-groups")
            ):
                directive_info["t-groups"] = repr(attrib["groups"])
            elif directive == "att":
                for key, value in attrib.items():
                    if key.startswith(("t-att-", "t-attf-")):
                        directive_info[key] = repr(value)
            elif directive == "options":
                for key, value in attrib.items():
                    if key.startswith("t-options-"):
                        directive_info[key] = repr(value)
            elif ("t-" + directive) not in attrib:
                directive_info["t-" + directive] = None

            execution_context = tools.profiler.ExecutionContext(
                **directive_info, xpath=xpath
            )
            execution_context.__enter__()
            self.context_stack.append(execution_context)

        for hook in self.qweb_hooks:
            hook(
                "enter",
                self.cr.sql_log_count,
                view_id=self.view_id,
                xpath=xpath,
                directive=directive,
                attrib=attrib,
            )

    def leave_directive(
        self, directive: str, attrib: dict[str, str], xpath: str
    ) -> None:
        if self.execution_context_enabled:
            self.context_stack.pop().__exit__()

        for hook in self.qweb_hooks:
            hook(
                "leave",
                self.cr.sql_log_count,
                view_id=self.view_id,
                xpath=xpath,
                directive=directive,
                attrib=attrib,
            )


class QwebCollector(Collector):
    """Record qweb execution with directive trace."""

    name = "qweb"

    def __init__(self):
        super().__init__()
        self.events = []

        def hook(event, sql_log_count, **kwargs):
            self.events.append((event, kwargs, sql_log_count, real_time()))

        self.hook = hook

    def _get_directive_profiling_name(self, directive, attrib):
        expr = ""
        if directive == "set":
            if "t-set" in attrib:
                expr = f"t-set={attrib['t-set']!r}"
                if "t-value" in attrib:
                    expr += f" t-value={attrib['t-value']!r}"
                if "t-valuef" in attrib:
                    expr += f" t-valuef={attrib['t-valuef']!r}"
            for key in attrib:
                if key.startswith(("t-set-", "t-setf-")):
                    if expr:
                        expr += " "
                    expr += f"{key}={attrib[key]!r}"
        elif directive == "foreach":
            expr = f"t-foreach={attrib['t-foreach']!r} t-as={attrib['t-as']!r}"
        elif directive == "options":
            if attrib.get("t-options"):
                expr = f"t-options={attrib['t-options']!r}"
            for key in attrib:
                if key.startswith("t-options-"):
                    expr = f"{expr}  {key}={attrib[key]!r}"
        elif directive == "att":
            for key in attrib:
                if key == "t-att" or key.startswith(("t-att-", "t-attf-")):
                    if expr:
                        expr += " "
                    expr += f"{key}={attrib[key]!r}"
        elif ("t-" + directive) in attrib:
            expr = f"t-{directive}={attrib['t-' + directive]!r}"
        else:
            expr = f"t-{directive}"

        return expr

    def start(self):
        init_thread = self.profiler.init_thread
        if not hasattr(init_thread, "qweb_hooks"):
            init_thread.qweb_hooks = []
        init_thread.qweb_hooks.append(self.hook)

    def stop(self):
        self.profiler.init_thread.qweb_hooks.remove(self.hook)

    def post_process(self):
        last_event_query = None
        last_event_time = None
        stack = []
        results = []
        archs = {}
        for event, kwargs, sql_count, event_time in self.events:
            if event == "render":
                archs[kwargs["view_id"]] = kwargs["arch"]
                continue

            # update the active directive with the elapsed time and queries
            if stack:
                top = stack[-1]
                top["delay"] += event_time - last_event_time
                top["query"] += sql_count - last_event_query
            last_event_time = event_time
            last_event_query = sql_count

            directive = self._get_directive_profiling_name(
                kwargs["directive"], kwargs["attrib"]
            )
            if directive:
                if event == "enter":
                    data = {
                        "view_id": kwargs["view_id"],
                        "xpath": kwargs["xpath"],
                        "directive": directive,
                        "delay": 0,
                        "query": 0,
                    }
                    results.append(data)
                    stack.append(data)
                else:
                    assert event == "leave"
                    data = stack.pop()

        self.add({"results": {"archs": archs, "data": results}})
        super().post_process()


class ExecutionContext:
    """Add contextual information on the thread at the current call-stack level.

    This context is stored by the collector alongside the stack and is used by
    Speedscope to add an extra stack level with this information.
    """

    def __init__(self, **context: Any) -> None:
        self.context: dict[str, Any] = context
        self.previous_context: tuple | None = None

    def __enter__(self) -> ExecutionContext:
        current_thread = threading.current_thread()
        self.previous_context = getattr(current_thread, "exec_context", ())
        current_thread.exec_context = self.previous_context + (
            (stack_size(), self.context),
        )
        return self

    def __exit__(self, *_args: Any) -> None:
        threading.current_thread().exec_context = self.previous_context


class Profiler:
    """Context manager that records execution; saves SQL and async stack traces by default."""

    def __init__(
        self,
        collectors: list[str | Collector] | None = None,
        db: str | None = ...,
        profile_session: str | None = None,
        description: str | None = None,
        disable_gc: bool = False,
        params: dict[str, Any] | None = None,
        log: bool = False,
    ) -> None:
        """
        :param db: database name for saving results; determined automatically by
            default. Pass ``None`` to skip saving.
        :param collectors: collector names or Collector objects, e.g.
            ``['sql', PeriodicCollector(interval=0.2)]``. ``None`` for the defaults.
        :param profile_session: session label to regroup multiple profiles; see
            make_session() for the default format.
        :param description: description of this profiler, e.g. route name, test
            method, or loading module.
        :param disable_gc: disable gc during profiling (avoids gc pauses, notably
            during SQL execution).
        :param params: parameters usable by collectors (e.g. frame interval).
        """
        self.start_time: float = 0
        self.duration: float = 0
        self.start_cpu_time: float = 0
        self.cpu_duration: float = 0
        self.profile_session: str = profile_session or make_session()
        self.description: str | None = description
        self.init_frame: FrameType | list | None = None
        self.init_stack_trace: list[tuple[str, int, str, str]] | list | None = None
        self.init_thread: threading.Thread | None = None
        self.disable_gc: bool = disable_gc
        self.filecache: dict[str, list[str] | None] = {}
        self.params: dict[str, Any] = (
            params or {}
        )  # custom parameters usable by collectors
        self.profile_id: int | None = None
        self.log: bool = log
        self.sub_profilers: list[Profiler] = []
        self.entry_count_limit: int = int(
            self.params.get("entry_count_limit", 0)
        )  # the limit could be set using a smarter way
        self.done: bool = False
        self.exit_stack: ExitStack = ExitStack()
        self.counter: int = 0

        if db is ...:
            # determine database from current thread
            db = getattr(threading.current_thread(), "dbname", None)
            if not db:
                # only raise if path is not given and db is not explicitely disabled
                msg = "Database name cannot be defined automaticaly. \n Please provide a valid/falsy dbname or path parameter"
                raise ValueError(msg)
        self.db: str | None = db

        # collectors
        if collectors is None:
            collectors = ["sql", "traces_async"]
        self.collectors: list[Collector] = []
        for collector in collectors:
            if isinstance(collector, str):
                try:
                    collector = Collector.make(collector)
                except Exception:
                    _logger.error("Could not create collector with name %r", collector)
                    continue
            collector.profiler = self
            self.collectors.append(collector)

    def __enter__(self) -> Profiler:
        self.init_thread = threading.current_thread()
        try:
            self.init_frame = get_current_frame(self.init_thread)
            self.init_stack_trace = _get_stack_trace(self.init_frame)
        except KeyError:
            # when using thread pools the thread won't exist in the current_frames
            # this case is managed by http.py but will still fail when adding a profiler
            # inside a piece of code that may be called by a longpolling route.
            # in this case, avoid crashing the caller and disable all collectors
            self.init_frame = self.init_stack_trace = self.collectors = []
            self.db = self.params = None
            message = "Cannot start profiler, thread not found. Is the thread part of a thread pool?"
            if not self.description:
                self.description = message
            _logger.warning(message)

        if self.description is None:
            frame = self.init_frame
            code = frame.f_code
            self.description = (
                f"{frame.f_code.co_name} ({code.co_filename}:{frame.f_lineno})"
            )
        if self.params:
            self.init_thread.profiler_params = self.params
        if self.disable_gc:
            self.exit_stack.enter_context(disabling_gc())
        self.start_time = real_time()
        self.start_cpu_time = real_cpu_time()
        for collector in self.collectors:
            collector.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self.end()

    def end(self) -> None:
        if self.done:
            return
        self.done = True
        try:
            for collector in self.collectors:
                collector.stop()
            self.duration = real_time() - self.start_time
            self.cpu_duration = real_cpu_time() - self.start_cpu_time
            self._add_file_lines(self.init_stack_trace)

            if self.db:
                # pylint: disable=import-outside-toplevel
                from odoo.db import (
                    db_connect,
                )  # only import from odoo if/when needed.

                with db_connect(self.db).cursor() as cr:
                    values = {
                        "name": self.description,
                        "session": self.profile_session,
                        "create_date": real_datetime_now(),
                        "init_stack_trace": json.dumps(
                            _format_stack(self.init_stack_trace)
                        ),
                        "duration": self.duration,
                        "cpu_duration": self.cpu_duration,
                        "entry_count": self.entry_count(),
                        "sql_count": sum(
                            len(collector.entries)
                            for collector in self.collectors
                            if collector.name == "sql"
                        ),
                    }
                    others = {}
                    for collector in self.collectors:
                        if collector.entries:
                            if collector._store == "others":
                                others[collector.name] = json.dumps(collector.entries)
                            else:
                                values[collector.name] = json.dumps(collector.entries)
                    if others:
                        values["others"] = json.dumps(others)
                    query = SQL(
                        "INSERT INTO ir_profile(%s) VALUES %s RETURNING id",
                        SQL(",").join(map(SQL.identifier, values)),
                        tuple(values.values()),
                    )
                    cr.execute(query)
                    self.profile_id = cr.fetchone()[0]
                    _logger.info(
                        "ir_profile %s (%s) created",
                        self.profile_id,
                        self.profile_session,
                    )
        except OperationalError:
            _logger.exception("Could not save profile in database")
        finally:
            self.exit_stack.close()
            if self.params:
                del self.init_thread.profiler_params
            if self.log:
                _logger.info(self.summary())

    def _get_cm_proxy(self) -> Nested:
        return Nested(self)

    def _add_file_lines(
        self, stack: list[tuple[str, int, str, str]] | list | None
    ) -> None:
        for index, frame in enumerate(stack):
            filename, lineno, name, line = frame
            if line != "":
                continue
            # retrieve file lines from the filecache
            if not lineno:
                continue
            try:
                filelines = self.filecache[filename]
            except KeyError:
                try:
                    with tools.file_open(filename, filter_ext=(".py",)) as f:
                        filelines = f.readlines()
                except (
                    ValueError,
                    FileNotFoundError,
                ):  # mainly for <decorator> "filename"
                    filelines = None
                self.filecache[filename] = filelines
            # fill in the line
            if filelines is not None and 0 < lineno <= len(filelines):
                line = filelines[lineno - 1]
                stack[index] = (filename, lineno, name, line)

    def entry_count(self) -> int:
        """Return the total number of entries collected in this profiler."""
        return sum(len(collector.entries) for collector in self.collectors)

    def format_path(self, path: str) -> str:
        """Format a path for this profiler, mainly to uniquify it between executions."""
        return path.format(
            time=real_datetime_now().strftime("%Y%m%d-%H%M%S"),
            len=self.entry_count(),
            desc=re.sub(r"[^0-9a-zA-Z-]+", "_", self.description),
        )

    def json(self) -> str:
        """Return a JSON representation of this profiler.

        Useful to write profiling entries to a file, such as::

            with Profiler(db=None) as profiler:
                do_stuff()

            filename = profiler.format_path("/home/foo/{desc}_{len}.json")
            with open(filename, "w") as f:
                f.write(profiler.json())
        """
        return json.dumps(
            {
                "name": self.description,
                "session": self.profile_session,
                "create_date": real_datetime_now().strftime("%Y%m%d-%H%M%S"),
                "init_stack_trace": _format_stack(self.init_stack_trace),
                "duration": self.duration,
                "collectors": {
                    collector.name: collector.entries for collector in self.collectors
                },
            },
            indent=4,
        )

    def summary(self) -> str:
        result = ""
        for profiler in [self, *self.sub_profilers]:
            for collector in profiler.collectors:
                result += f"\n{self.description}\n{collector.summary()}"
        return result


class Nested:
    """Nest another context manager inside a profiler.

    The profiler must be entered directly by the ``with``, not wrapped in an
    ExitStack: otherwise ``init_frame`` retrieval can be wrong and profiling
    fails with "Limit frame was not found". Frames inside this file are ignored
    by the stack walk, so the nested frames are skipped too — which is also why
    this does not use ``contextlib.contextmanager``.
    """

    def __init__(self, profiler: Profiler, context_manager: Any = None) -> None:
        self._profiler__: Profiler = profiler
        self.context_manager: Any = context_manager or nullcontext()

    def __enter__(self) -> Any:
        self._profiler__.__enter__()
        return self.context_manager.__enter__()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> bool | None:
        try:
            return self.context_manager.__exit__(exc_type, exc_value, traceback)
        finally:
            self._profiler__.__exit__(exc_type, exc_value, traceback)
