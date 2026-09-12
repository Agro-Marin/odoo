from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class LoadingPhase:
    reinit_modules: set[str] = field(default_factory=set)
    xmlids_written: set[str] = field(default_factory=set)
    xmlid_recorder: set[str] | None = None
    load_language_done: bool = False
