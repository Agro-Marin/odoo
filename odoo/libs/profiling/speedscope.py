"""Export collected profiling data to the speedscope.app file format."""

__all__ = ["Speedscope"]

import reprlib
from collections.abc import Iterable
from typing import Any, Self

shortener = reprlib.Repr()
shortener.maxstring = 150
shorten = shortener.repr

# A frame tuple: (method_name, file_or_call_site, line_number_or_empty[, source_line])
type _Frame = tuple[Any, ...]
# A profile entry dict with keys like "stack", "start", "time", "query", etc.
type _Entry = dict[str, Any]
# A speedscope event dict with keys "type", "frame", "at"
type _Event = dict[str, Any]


class Speedscope:
    """Collect profiler entries and render them as a speedscope JSON document."""

    def __init__(
        self, name: str = "Speedscope", init_stack_trace: list[_Frame] | None = None
    ) -> None:
        """Build a Speedscope document named ``name`` rooted at ``init_stack_trace``."""
        self.init_stack_trace: list[_Frame] = init_stack_trace or []
        self.init_stack_trace_level: int = len(self.init_stack_trace)
        self.caller_frame: _Frame | None = None
        self.convert_stack(self.init_stack_trace)

        self.init_caller_frame: _Frame | None = None
        if self.init_stack_trace:
            self.init_caller_frame = self.init_stack_trace[-1]
        self.profiles_raw: dict[str, list[_Entry]] = {}
        self.name: str = name
        self.frames_indexes: dict[_Frame, int] = {}
        self.frame_count: int = 0
        self.profiles: list[dict[str, Any]] = []

    def add(self, key: str, profile: list[_Entry]) -> None:
        """Register ``profile`` under ``key``, normalizing stacks and sql frames."""
        for entry in profile:
            self.caller_frame = self.init_caller_frame
            self.convert_stack(entry["stack"] or [])
            if "query" in entry:
                query = entry["query"]
                full_query = entry["full_query"]
                entry["stack"].append((f"sql({shorten(query)})", full_query, None))
        self.profiles_raw[key] = profile

    def convert_stack(self, stack: list[_Frame]) -> None:
        """Rewrite each frame of ``stack`` in place to a ``(method, line, number)`` tuple."""
        for index, frame in enumerate(stack):
            method = frame[2]
            line = ""
            number = ""
            if self.caller_frame and len(self.caller_frame) == 4:
                line = (
                    f"called at {self.caller_frame[0]} ({self.caller_frame[3].strip()})"
                )
                number = self.caller_frame[1]
            stack[index] = (
                method,
                line,
                number,
            )
            self.caller_frame = frame

    def add_output(
        self,
        names: Iterable[str],
        complete: bool = True,
        display_name: str | None = None,
        use_context: bool = True,
        constant_time: bool = False,
        context_per_name: dict[str, Any] | None = None,
        **params: Any,
    ) -> Self:
        """Add a profile output to the list of profiles.

        :param names: list of keys to combine in this output. Keys correspond to the ones used in add
        :param display_name: name of the tab for this output
        :param complete: display the complete stack. If False, don't display the stack below the profiler.
        :param use_context: use execution context (added by ExecutionContext context manager) to display the profile.
        :param constant_time: hide temporality. Useful to compare query counts
        :param context_per_name: a dictionary of additional context per name.
        """
        entries = []
        display_name = display_name or ",".join(names)
        for name in names:
            raw = self.profiles_raw.get(name)
            if not raw:
                continue
            entries += raw
        entries.sort(key=lambda e: e["start"])
        result = self.process(
            entries,
            use_context=use_context,
            constant_time=constant_time,
            **params,
        )
        if not result:
            return self
        start = result[0]["at"]
        end = result[-1]["at"]

        if complete:
            init_stack_trace_ids = self.stack_to_ids(
                self.init_stack_trace,
                use_context and entries[0].get("exec_context"),
            )
            start_stack = [
                {"type": "O", "frame": frame_id, "at": start}
                for frame_id in init_stack_trace_ids
            ]
            end_stack = [
                {"type": "C", "frame": frame_id, "at": end}
                for frame_id in reversed(init_stack_trace_ids)
            ]
            result = start_stack + result + end_stack

        self.profiles.append(
            {
                "name": display_name,
                "type": "evented",
                "unit": "entries" if constant_time else "seconds",
                "startValue": 0,
                "endValue": end - start,
                "events": result,
            }
        )
        return self

    def add_default(self, **params: Any) -> Self:
        """Add the default set of outputs for the collected profiles per ``params``."""
        if len(self.profiles_raw) > 1:
            if params["combined_profile"]:
                self.add_output(
                    list(self.profiles_raw), display_name="Combined", **params
                )
        for key, profile in self.profiles_raw.items():
            sql = profile and profile[0].get("query")
            if sql:
                if params["sql_no_gap_profile"]:
                    self.add_output(
                        [key],
                        hide_gaps=True,
                        display_name=f"{key} (no gap)",
                        **params,
                    )
                if params["sql_density_profile"]:
                    self.add_output(
                        [key],
                        continuous=False,
                        complete=False,
                        display_name=f"{key} (density)",
                        **params,
                    )

            elif params["frames_profile"]:
                self.add_output([key], display_name=key, **params)
        return self

    def make(self, **params: Any) -> dict[str, Any]:
        """Build and return the complete speedscope document as a dict."""
        if not self.profiles:
            self.add_default(**params)
        return {
            "name": self.name,
            "activeProfileIndex": 0,
            "$schema": "https://www.speedscope.app/file-format-schema.json",
            "shared": {
                "frames": [
                    {"name": frame[0], "file": frame[1], "line": frame[2]}
                    for frame in self.frames_indexes
                ]
            },
            "profiles": self.profiles,
        }

    def get_frame_id(self, frame: _Frame) -> int:
        """Return the id of ``frame``, registering it on first use."""
        if frame not in self.frames_indexes:
            self.frames_indexes[frame] = self.frame_count
            self.frame_count += 1
        return self.frames_indexes[frame]

    def stack_to_ids(
        self,
        stack: list[_Frame],
        context: Any,
        aggregate_sql: bool = False,
        stack_offset: int = 0,
    ) -> list[int]:
        """Assemble stack and context into a list of frame ids.

        Add each corresponding context at the corresponding level.

        :param stack: A list of hashable frame
        :param context: an iterable of (level, value) ordered by level
        :param stack_offset: offset level for stack
        """
        stack_ids = []
        context_iterator = iter(context or ())
        context_level, context_value = next(context_iterator, (None, None))
        # consume iterator until we are over stack_offset
        while context_level is not None and context_level < stack_offset:
            context_level, context_value = next(context_iterator, (None, None))
        for level, frame in enumerate(stack, start=stack_offset + 1):
            if aggregate_sql:
                frame = (frame[0], "", frame[2])
            while context_level == level:
                context_frame = (
                    ", ".join(f"{k}={v}" for k, v in context_value.items()),
                    "",
                    "",
                )
                stack_ids.append(self.get_frame_id(context_frame))
                context_level, context_value = next(context_iterator, (None, None))
            stack_ids.append(self.get_frame_id(frame))
        return stack_ids

    def process(
        self,
        entries: list[_Entry],
        continuous: bool = True,
        hide_gaps: bool = False,
        use_context: bool = True,
        constant_time: bool = False,
        aggregate_sql: bool = False,
        **params: Any,
    ) -> list[_Event]:
        """Turn ``entries`` into a list of speedscope open/close events."""
        # constant_time parameters is mainly useful to hide temporality when focussing on sql determinism
        entry_end = previous_end = None
        if not entries:
            return []
        events = []
        current_stack_ids = []
        frames_start = entries[0]["start"]

        # add last closing entry if missing
        last_entry = entries[-1]
        if last_entry["stack"]:
            entries.append(
                {
                    "stack": [],
                    "start": last_entry["start"] + last_entry.get("time", 0),
                }
            )

        for index, entry in enumerate(entries):
            if constant_time:
                entry_start = close_time = index
            else:
                previous_end = entry_end
                if hide_gaps and previous_end:
                    entry_start = previous_end
                else:
                    entry_start = entry["start"] - frames_start

                if previous_end and previous_end > entry_start:
                    # skip entry if entry starts after another entry end
                    continue

                if previous_end:
                    close_time = min(entry_start, previous_end)
                else:
                    close_time = entry_start

                entry_time = entry.get("time")
                entry_end = None if entry_time is None else entry_start + entry_time

            entry_stack_ids = self.stack_to_ids(
                entry["stack"] or [],
                use_context and entry.get("exec_context"),
                aggregate_sql,
                self.init_stack_trace_level,
            )
            level = 0
            if continuous:
                level = -1
                for current, new in zip(
                    current_stack_ids, entry_stack_ids, strict=False
                ):
                    level += 1
                    if current != new:
                        break
                else:
                    level += 1

            events.extend(
                {"type": "C", "frame": frame, "at": close_time}
                for frame in reversed(current_stack_ids[level:])
            )
            events.extend(
                {"type": "O", "frame": frame, "at": entry_start}
                for frame in entry_stack_ids[level:]
            )
            current_stack_ids = entry_stack_ids

        return events
