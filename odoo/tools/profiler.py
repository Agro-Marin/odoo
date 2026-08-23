import json
import logging
import re
import sys
import threading
import time
import tracemalloc
import types
from contextlib import ExitStack, nullcontext
from datetime import datetime
from typing import TYPE_CHECKING, Any, Self

from psycopg import OperationalError

from odoo import tools
from odoo.libs.gc import disabling_gc
from odoo.libs.worker_thread import current_worker_thread
from odoo.tools import SQL

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import FrameType

_logger = logging.getLogger(__name__)

real_datetime_now = datetime.now
real_time = time.time.__call__
real_cpu_time = time.thread_time.__call__


def _format_frame(frame: FrameType) -> tuple[str, int, str, str]:
    code = frame.f_code
    return (code.co_filename, frame.f_lineno, code.co_name, "")


def _format_stack(stack: list[tuple[str, int, str, str]]) -> list[list[Any]]:
    return [list(frame) for frame in stack]


def get_current_frame(thread: threading.Thread | None = None) -> FrameType:
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
    stack = []
    while frame is not None and frame != limit_frame:
        stack.append(_format_frame(frame))
        frame = frame.f_back
    if frame is None and limit_frame:
        _logger.runbot("Limit frame was not found")
    return list(reversed(stack))


def stack_size() -> int:
    frame = get_current_frame()
    size = 0
    while frame:
        size += 1
        frame = frame.f_back
    return size


def make_session(name: str = "") -> str:
    return f"{real_datetime_now():%Y-%m-%d %H:%M:%S} {name}"


def force_hook() -> None:
    thread = threading.current_thread()
    for func in getattr(thread, "profile_hooks", ()):
        func()


class Collector:
    name: str = ""
    _store: str | None = None
    _registry: dict[str, type[Collector]] = {}

    @classmethod
    def __init_subclass__(cls):
        if cls.name:
            cls._registry[cls.name] = cls
            cls._registry[cls.__name__] = cls

    @classmethod
    def make(cls, name: str, *args: Any, **kwargs: Any) -> Collector:
        return cls._registry[name](*args, **kwargs)

    def __init__(self) -> None:
        self._processed: bool = False
        self._entries: list[dict[str, Any]] = []
        self.processed_entries: list[dict[str, Any]] = []
        self._profiler: Profiler | None = None

    @property
    def profiler(self) -> Profiler:
        """The profiler this collector belongs to.

        A collector is built before the profiler that owns it -- `Profiler.
        __init__` constructs the list, then assigns itself to each -- so every
        method that reaches for `self.profiler` is reaching for something that
        was None a moment earlier. Declared as `Profiler | None` that made the
        whole class unanalysable: 48 of this module's type errors were one
        `Optional` propagating through every use. The window is real but tiny,
        and landing in it is a construction bug, so say so once here instead of
        guarding at each of the forty-eight.
        """
        if self._profiler is None:
            msg = (
                f"{type(self).__name__} has no profiler yet: a collector is "
                f"usable only once a Profiler has adopted it."
            )
            raise RuntimeError(msg)
        return self._profiler

    @profiler.setter
    def profiler(self, profiler: Profiler) -> None:
        self._profiler = profiler

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def add(
        self,
        entry: dict[str, Any] | None = None,
        frame: FrameType | None = None,
    ) -> None:
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
        if (
            self.profiler.entry_count_limit
            and self.profiler.counter >= self.profiler.entry_count_limit
        ):
            if threading.current_thread() is self.profiler.init_thread:
                self.profiler.end()
            return
        self.profiler.counter += 1
        self.add(entry=entry, frame=frame)

    def _get_stack_trace(
        self, frame: FrameType | None = None
    ) -> list[tuple[str, int, str, str]] | None:
        frame = frame or get_current_frame(self.profiler.init_thread)
        return _get_stack_trace(frame, self.profiler.init_frame)

    def post_process(self) -> None:
        for entry in self._entries:
            stack = entry.get("stack", [])
            self.profiler._add_file_lines(stack)

    @property
    def entries(self) -> list[dict[str, Any]]:
        if not self._processed:
            self.post_process()
            self.processed_entries = self._entries
            # Hand the list over rather than blanking the attribute: `_entries`
            # used to become None here, so every later `.append` was an
            # AttributeError waiting on a caller that collected after reading.
            self._entries = []
            self._processed = True
        return self.processed_entries

    def summary(self) -> str:
        entries = self.processed_entries if self._processed else self._entries
        return f"{'=' * 10} {self.name} {'=' * 10} \n Entries: {len(entries)}"


class SQLCollector(Collector):
    name = "sql"

    def start(self) -> None:
        init_thread = self.profiler.init_thread
        if not hasattr(init_thread, "query_hooks"):
            init_thread.query_hooks = []
        init_thread.query_hooks.append(self.hook)

    def stop(self) -> None:
        self.profiler.init_thread.query_hooks.remove(self.hook)

    def hook(
        self,
        cr: Any,
        query: Any,
        params: Any,
        query_start: float,
        query_time: float,
    ) -> None:
        self.progress(
            {
                "query": str(query),
                "full_query": str(cr._format(query, params)),
                "start": query_start,
                "time": query_time,
            }
        )

    def summary(self) -> str:
        entries = self.processed_entries if self._processed else self._entries
        total_time = sum(entry["time"] for entry in entries) or 1
        sql_entries = []
        for entry in entries:
            bar = "*" * int(entry["time"] / total_time * 100)
            sql_entries.append(
                f"\n{'-' * 100}\n{entry['time']}  {bar}\n{entry['full_query']}"
            )
        return super().summary() + "".join(sql_entries)


class _BasePeriodicCollector(Collector):
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
        self.active = True
        self._last_time = real_time()
        while self.active:
            self.progress()
            self._stop_event.wait(self.frame_interval)

    def stop(self) -> None:
        self.active = False
        self._stop_event.set()
        self._entries.append({"stack": [], "start": real_time()})
        if self.__thread.is_alive() and self.__thread is not threading.current_thread():
            self.__thread.join()
        self.profiler.init_thread.profile_hooks.remove(self.progress)


class PeriodicCollector(_BasePeriodicCollector):
    name = "traces_async"

    def add(self, entry=None, frame=None):
        if self.last_frame:
            duration = real_time() - self._last_time
            if duration > self.frame_interval * 10:
                self._entries[-1]["stack"].append(
                    (
                        "profiling",
                        0,
                        "⚠ Profiler freezed for %s s" % duration,
                        "",
                    )
                )
                self.last_frame = None
        self._last_time = real_time()

        frame = frame or get_current_frame(self.profiler.init_thread)
        if frame == self.last_frame:
            return
        self.last_frame = frame
        super().add(entry=entry, frame=frame)


_lock = threading.Lock()


class MemoryCollector(_BasePeriodicCollector):
    name = "memory"
    _store = "others"
    _min_interval = 0.01
    _default_interval = 1
    _lock_acquired = False

    def start(self):
        self._lock_acquired = _lock.acquire(timeout=5)
        if not self._lock_acquired:
            _logger.warning(
                "Memory collector not started: another memory collector is "
                "already active in this process"
            )
            return
        try:
            tracemalloc.start()
            super().start()
        except BaseException:
            _lock.release()
            self._lock_acquired = False
            raise

    def add(self, entry=None, frame=None):
        self._entries.append(
            {
                "start": real_time(),
                "memory": tracemalloc.take_snapshot(),
            }
        )

    def stop(self):
        if not self._lock_acquired:
            return
        try:
            super().stop()
            tracemalloc.stop()
        finally:
            _lock.release()
            self._lock_acquired = False

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
    name = "traces_sync"

    def start(self):
        # Refuse rather than displace. This used to log the clash and call
        # settrace anyway, silently unhooking whatever held it -- a debugger,
        # coverage -- and stop() then set None instead of putting it back.
        if (existing := sys.gettrace()) is not None:
            msg = (
                f"Cannot start SyncCollector: sys.settrace is already set to "
                f"{existing!r}. Profiling would silently disable it."
            )
            raise RuntimeError(msg)
        if self._processed:
            msg = "You cannot start SyncCollector after accessing entries."
            raise RuntimeError(msg)
        sys.settrace(self.hook)

    def stop(self):
        if sys.gettrace() is self.hook:
            sys.settrace(None)

    def hook(self, _frame, event, _arg=None):
        if event == "line":
            return None
        entry = {"event": event, "frame": _format_frame(_frame)}
        if event == "call" and _frame.f_back:
            entry["parent_frame"] = _format_frame(_frame.f_back)
        self.progress(entry, frame=_frame)
        return self.hook

    def _get_stack_trace(self, frame=None):
        return None

    def post_process(self):
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
            entry["stack"] = stack.copy()
        super().post_process()


class QwebTracker:
    def __init__(self, view_id: int, arch: Any, cr: Any) -> None:
        current_thread = threading.current_thread()
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
                elif event == "leave":
                    stack.pop()
                else:
                    raise ValueError(f"unexpected qweb event {event!r}")

        self.add({"results": {"archs": archs, "data": results}})
        super().post_process()


class ExecutionContext:
    def __init__(self, **context: Any) -> None:
        self.context: dict[str, Any] = context
        self.previous_context: tuple | None = None

    def __enter__(self) -> Self:
        current_thread = threading.current_thread()
        self.previous_context = getattr(current_thread, "exec_context", ())
        current_thread.exec_context = self.previous_context + (
            (stack_size(), self.context),
        )
        return self

    def __exit__(self, *_args: object) -> None:
        current_worker_thread().exec_context = self.previous_context


class Profiler:
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
        self.params: dict[str, Any] = params or {}
        self.profile_id: int | None = None
        self.log: bool = log
        self.sub_profilers: list[Profiler] = []
        self.entry_count_limit: int = int(self.params.get("entry_count_limit", 0))
        self.done: bool = False
        self._end_lock: threading.Lock = threading.Lock()
        self.exit_stack: ExitStack = ExitStack()
        self.counter: int = 0

        if db is ...:
            db = getattr(current_worker_thread(), "dbname", None)
            if not db:
                msg = "Database name cannot be defined automaticaly. \n Please provide a valid/falsy dbname or path parameter"
                raise ValueError(msg)
        self.db: str | None = db

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

    def __enter__(self) -> Self:
        self.init_thread = threading.current_thread()
        try:
            self.init_frame = get_current_frame(self.init_thread)
            self.init_stack_trace = _get_stack_trace(self.init_frame)
        except KeyError:
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
        started = []
        try:
            for collector in self.collectors:
                collector.start()
                started.append(collector)
        except BaseException:
            for collector in reversed(started):
                try:
                    collector.stop()
                except Exception:
                    _logger.exception(
                        "Failed to stop collector %s during profiler start rollback",
                        collector,
                    )
            raise
        return self

    def __exit__(self, *args: object) -> None:
        self.end()

    def end(self) -> None:
        with self._end_lock:
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
                from odoo.db import (
                    db_connect,
                )

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
            if (
                self.params
                and getattr(self.init_thread, "profiler_params", None) is self.params
            ):
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
                ):
                    filelines = None
                self.filecache[filename] = filelines
            if filelines is not None and 0 < lineno <= len(filelines):
                line = filelines[lineno - 1]
                stack[index] = (filename, lineno, name, line)

    def entry_count(self) -> int:
        return sum(len(collector.entries) for collector in self.collectors)

    def format_path(self, path: str) -> str:
        return path.format(
            time=real_datetime_now().strftime("%Y%m%d-%H%M%S"),
            len=self.entry_count(),
            desc=re.sub(r"[^0-9a-zA-Z-]+", "_", self.description),
        )

    def json(self) -> str:
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
        traceback: types.TracebackType | None,
    ) -> bool | None:
        try:
            return self.context_manager.__exit__(exc_type, exc_value, traceback)
        finally:
            self._profiler__.__exit__(exc_type, exc_value, traceback)
