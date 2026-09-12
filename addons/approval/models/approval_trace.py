"""Campaign instrumentation for the approval engine.

TEMPORARY SCAFFOLDING. This module, every ``trace.*`` call site in the addon and
the ``CALL_TRACES`` table below exist for one campaign -- code quality,
maintainability, performance and lifecycle work on ``approval`` -- and they are
removed when it ends. ``machine_doc_v1/conventions.md`` ("Campaign
instrumentation") is the reference: the target table, the level discipline, the
switches and the removal recipe.

Two switches, and both must be open for a line to reach a log:

1. The target's level. Every logger here is ``odoo.approval.<target>``, kept
   QUIET BY DEFAULT (``WARNING``) so an ordinary server or test run prints
   nothing, even under ``--log-level=debug``. Name what you want:
   ``--log-handler odoo.approval:DEBUG`` for everything,
   ``--log-handler odoo.approval.routing:DEBUG`` for one target. A target
   explicitly configured wins over this module's default, whichever order they
   happen in, because ``_quiet_by_default`` only sets a level nobody set.
2. For per-item floods, the ``odoo.approval.<target>.items`` child, which a
   parent at DEBUG enables too; silence one with
   ``--log-handler odoo.approval.routing.items:INFO``.

Nothing here may change behaviour. Rendering never touches a field and degrades
to a marker instead of raising, the wrappers return what they wrapped, and no
target emits above INFO -- a real warning belongs on the module logger of the
file that found it, not on a campaign target that a future session deletes.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from functools import wraps
from typing import Any

from odoo import models

LOG_ROOT = "odoo.approval"
TRACE_ORIGIN = "_approval_trace_origin"

_QUIET_DEFAULT = logging.WARNING
_MAX_IDS = 10
_MAX_ITEMS = 50
_MAX_CHARS = 200

_depth = threading.local()
_perf: dict[str, list[float]] = {}


# -- rendering -----------------------------------------------------------------


def _render_ids(ids: Iterable[Any]) -> str:
    shown = list(ids)[: _MAX_IDS + 1]
    if len(shown) > _MAX_IDS:
        return f"[{','.join(str(i) for i in shown[:_MAX_IDS])},+]"
    return f"[{','.join(str(i) for i in shown)}]"


def _render_value(value: Any) -> str:
    if isinstance(value, models.BaseModel):
        if len(value) == 1 and value.id:
            return f"{value._name}#{value.id}"
        return f"{value._name}#{_render_ids(value._ids)}"
    if value is None or isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, Mapping):
        inner = ",".join(
            f"{key}:{_render_value(item)}"
            for key, item in list(value.items())[:_MAX_IDS]
        )
        return f"{{{inner}}}"
    if isinstance(value, (set, frozenset)):
        return _render_ids(sorted(value, key=repr))
    if isinstance(value, (list, tuple)):
        return _render_ids(_render_value(item) for item in value)
    text = str(value)
    if len(text) > _MAX_CHARS:
        text = f"{text[:_MAX_CHARS]}..."
    return text if text and not any(char.isspace() for char in text) else repr(text)


def _render(value: Any) -> str:
    try:
        return _render_value(value)
    except Exception:  # instrumentation must never break the engine
        return "<unrenderable>"


def _line(event: str, fields: Mapping[str, Any]) -> str:
    if not fields:
        return event
    rendered = " ".join(f"{key}={_render(value)}" for key, value in fields.items())
    return f"{event} {rendered}"


# -- one target ----------------------------------------------------------------


class _OffSpan(dict):
    """The span mapping handed out when the target is off: writes go nowhere."""

    def __setitem__(self, key: Any, value: Any) -> None:
        pass


_OFF_SPAN = _OffSpan()


class Target:
    """One campaign log target, ``odoo.approval.<name>``."""

    __slots__ = ("_items_logger", "_logger", "name")

    def __init__(self, name: str) -> None:
        self.name = name
        self._logger = logging.getLogger(f"{LOG_ROOT}.{name}")
        self._items_logger = logging.getLogger(f"{LOG_ROOT}.{name}.items")

    def on(self) -> bool:
        """Whether a payload is worth building at all."""
        return self._logger.isEnabledFor(logging.DEBUG)

    def items_on(self) -> bool:
        return self._items_logger.isEnabledFor(logging.DEBUG)

    def note(self, event: str, **fields: Any) -> None:
        """INFO: one line per externally visible lifecycle event."""
        if self._logger.isEnabledFor(logging.INFO):
            self._logger.info(_line(event, fields))

    def event(self, event: str, **fields: Any) -> None:
        """DEBUG: one line per decision this code took."""
        if self._logger.isEnabledFor(logging.DEBUG):
            self._logger.debug(_line(event, fields))

    def items(
        self,
        event: str,
        entries: Iterable[Mapping[str, Any]]
        | Callable[[], Iterable[Mapping[str, Any]]],
    ) -> None:
        """DEBUG on ``<target>.items``: one line per item of a batch.

        ``entries`` may be a callable so that a caller pays nothing for building
        the payload while the child logger is silent.
        """
        if not self._items_logger.isEnabledFor(logging.DEBUG):
            return
        resolved = entries() if callable(entries) else entries
        for index, entry in enumerate(resolved):
            if index >= _MAX_ITEMS:
                self._items_logger.debug(_line(event, {"truncated_after": _MAX_ITEMS}))
                return
            self._items_logger.debug(_line(event, {"i": index, **entry}))

    @contextmanager
    def span(self, event: str, **fields: Any) -> Iterator[dict[str, Any]]:
        """Time a block and log it once, whether it returns or raises.

        Yields the field mapping so the body can add what it learns
        (``span["rows"] = len(rows)``).
        """
        if not self._logger.isEnabledFor(logging.DEBUG):
            yield _OFF_SPAN
            return
        depth = getattr(_depth, "value", 0)
        _depth.value = depth + 1
        spanned: dict[str, Any] = dict(fields)
        outcome = "ok"
        started = time.perf_counter()
        try:
            yield spanned
        except Exception as error:
            outcome = f"raised:{type(error).__name__}"
            raise
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            _depth.value = depth
            _account(event, elapsed_ms)
            self._logger.debug(
                _line(event, {**spanned, "ms": elapsed_ms, "d": depth, "r": outcome}),
            )


# -- the targets ---------------------------------------------------------------
#
# One per concern, so a campaign session enables the axis it is working on rather
# than the whole engine. Keep this list and the table in conventions.md together.

ACCESS = Target("access")
ACTIVITY = Target("activity")
ATTACHMENT = Target("attachment")
BINDING = Target("binding")
BUTTON = Target("button")
COMPUTE = Target("compute")
CRON = Target("cron")
CRUD = Target("crud")
DECISION = Target("decision")
DELEGATION = Target("delegation")
DOCUMENT = Target("document")
EDITOR = Target("editor")
ESCALATION = Target("escalation")
LIFECYCLE = Target("lifecycle")
MIXIN = Target("mixin")
PERF = Target("perf")
PREDICTION = Target("prediction")
REFUSAL = Target("refusal")
REGISTRY = Target("registry")
REPORT = Target("report")
ROUTING = Target("routing")
RULES = Target("rules")
SEARCH = Target("search")
SNAPSHOT = Target("snapshot")
STEPS = Target("steps")
SUBJECTS = Target("subjects")
SYNC = Target("sync")
TEMPLATE = Target("template")
WIZARD = Target("wizard")

_BY_NAME: dict[str, Target] = {
    target.name: target
    for target in (
        ACCESS,
        ACTIVITY,
        ATTACHMENT,
        BINDING,
        BUTTON,
        COMPUTE,
        CRON,
        CRUD,
        DECISION,
        DELEGATION,
        DOCUMENT,
        EDITOR,
        ESCALATION,
        LIFECYCLE,
        MIXIN,
        PERF,
        PREDICTION,
        REFUSAL,
        REGISTRY,
        REPORT,
        ROUTING,
        RULES,
        SEARCH,
        SNAPSHOT,
        STEPS,
        SUBJECTS,
        SYNC,
        TEMPLATE,
        WIZARD,
    )
}


def _quiet_by_default() -> None:
    """Keep the campaign silent unless a target was named on the command line.

    ONLY the root is levelled. ``--log-handler`` is resolved before any addon is
    imported, so a root the operator asked for already carries its own level and
    is left alone -- and every target is left at NOTSET so that it inherits that
    root, which is what makes ``--log-handler odoo.approval:DEBUG`` reach all of
    them while ``--log-handler odoo.approval.routing:DEBUG`` reaches one.
    """
    root = logging.getLogger(LOG_ROOT)
    if root.level == logging.NOTSET:
        root.setLevel(_QUIET_DEFAULT)


_quiet_by_default()


# -- the perf ledger -----------------------------------------------------------


def _account(event: str, elapsed_ms: float) -> None:
    entry = _perf.get(event)
    if entry is None:
        _perf[event] = [1, elapsed_ms, elapsed_ms]
        return
    entry[0] += 1
    entry[1] += elapsed_ms
    entry[2] = max(entry[2], elapsed_ms)


def perf_ledger() -> list[tuple[str, int, float, float]]:
    """Every span seen so far: event, calls, total ms, slowest ms."""
    return sorted(
        (
            (event, int(calls), total, worst)
            for event, (calls, total, worst) in _perf.items()
        ),
        key=lambda row: row[2],
        reverse=True,
    )


def dump_perf_ledger(reset: bool = True) -> None:
    """Log the ledger to ``odoo.approval.perf`` at INFO, then clear it.

    Meant to be called from a shell after exercising a flow, or at the end of a
    batch that is itself the thing being measured.
    """
    for event, calls, total, worst in perf_ledger():
        PERF.note(
            "ledger",
            call=event,
            calls=calls,
            total_ms=total,
            worst_ms=worst,
            avg_ms=total / calls,
        )
    if reset:
        _perf.clear()


# -- the wrapped entry points --------------------------------------------------
#
# model -> method -> target. Wrapping happens at registry load (approval's
# `base._register_hook`, models.py), so the engine's own files carry no line for
# any of it: one span per call with its batch size, duration, query delta and
# outcome. ONLY CONCRETE MODELS BELONG HERE -- an adopter of `mixin.approval`
# inherits the mixin's Python class, not its registry class, so wrapping an
# abstract model reaches nobody and the mixins are instrumented by hand instead.

CALL_TRACES: dict[str, dict[str, str]] = {
    "approval.request": {
        "create": "crud",
        "write": "crud",
        "unlink": "crud",
        "copy": "crud",
        "copy_data": "crud",
        "action_confirm": "lifecycle",
        "action_approve": "lifecycle",
        "action_refuse": "lifecycle",
        "action_cancel": "lifecycle",
        "action_reset_to_draft": "lifecycle",
        "action_resubmit": "lifecycle",
        "action_request_change": "lifecycle",
        "action_withdraw": "lifecycle",
        "action_withdraw_approver": "lifecycle",
        "action_approve_bulk": "lifecycle",
        "action_refuse_bulk": "lifecycle",
        "_action_bulk_decision": "lifecycle",
        "_apply_decision": "decision",
        "_force_terminal": "lifecycle",
        "_force_draft": "lifecycle",
        "_revoke": "lifecycle",
        "_approve_without_decision": "lifecycle",
        "_open_approval_round": "lifecycle",
        "_refuse_cascade": "lifecycle",
        "_withdraw_decided_steps": "decision",
        "_sync_approvers": "routing",
        "_extend_approvers_live": "routing",
        "_compute_desired_approvers": "routing",
        "_prepare_category_snapshot": "snapshot",
        "_check_auto_action_rules": "rules",
        "_find_matching_replacement": "rules",
        "_matched_add_approver_rules": "rules",
        "_get_applicable_steps": "steps",
        "_get_step_assignment": "steps",
        "_get_unmet_steps": "steps",
        "cron_smart_escalation": "cron",
        "cron_auto_expire": "cron",
        "cron_consent_approval": "cron",
        "_send_reminder": "escalation",
        "_escalate_to_manager": "escalation",
        "_reconcile_delegation_activities": "escalation",
        "_compute_state": "compute",
        "_compute_sla_status": "compute",
        "_compute_approval_progress": "compute",
        "_compute_pending_approver_ids": "compute",
        "_compute_res_name": "compute",
        "_compute_can_withdraw": "compute",
        "_compute_is_pending_my_review": "compute",
        "_compute_user_ids": "compute",
        "_compute_count_attachment": "compute",
        "_search_is_pending_my_review": "search",
        "_search_is_overdue": "search",
        "_search_sla_status": "search",
        "_predict_outcomes": "prediction",
        "_replay_bound_operation": "binding",
        "_check_access_write": "access",
        "_check_access_unlink": "access",
        "_check_locked_fields": "access",
        "_check_business_rules_unlink": "access",
        "_check_confirm": "lifecycle",
        "_retire_unasked_approval_activities": "activity",
        "_cancel_activities": "activity",
        "_lock_for_approval_action": "lifecycle",
    },
    "approval.approver": {
        "create": "crud",
        "write": "crud",
        "unlink": "crud",
        "action_approve": "decision",
        "action_refuse": "decision",
        "_create_activity": "activity",
        "_approve_for_every_step": "decision",
        "_compute_is_delegated": "delegation",
        "_get_effective_approver": "delegation",
        "_check_access_create": "access",
        "_check_access_write": "access",
        "_check_access_unlink": "access",
    },
    "approval.category": {
        "create": "crud",
        "write": "crud",
        "create_request": "lifecycle",
        "_compute_kanban_dashboard": "compute",
        "_compute_count_request_to_validate": "compute",
        "_compute_minimum_validity": "compute",
    },
    "approval.category.step": {
        "_get_pool_user_ids": "steps",
        "_get_candidate_user_ids": "steps",
        "_is_applicable_to_request": "steps",
        "_is_applicable_to_document": "steps",
    },
    "approval.rule": {
        "_evaluate": "rules",
        "_get_approver_tuples": "rules",
    },
    "approval.binding": {
        "_register_hook": "registry",
        "_unregister_hook": "registry",
        "_apply_to_registry": "registry",
        "_gate": "binding",
        "_admit": "binding",
        "_enforce_at_checkpoint": "binding",
        "_raise_requests_for": "binding",
        "_replay": "binding",
        "_reset_coverage": "binding",
        "_sync_reset_automation": "binding",
        "_approve_on_invoke": "binding",
        "get_button_approvals": "button",
        "check_button_approval": "button",
        "action_decide_approval": "button",
        "action_withdraw_decision": "button",
        "create_step_for_button": "editor",
        "action_open_button_steps": "editor",
    },
    "approval.template": {
        "action_create_request": "template",
    },
    "approval.decision.wizard": {
        "action_confirm_refuse": "wizard",
        "action_confirm_change": "wizard",
    },
    "approval.delegate.wizard": {
        "action_confirm": "wizard",
        "_compute_preview": "wizard",
    },
    "approval.dashboard": {
        "get_dashboard": "report",
        "action_refresh": "report",
        "_compute_today_stats": "report",
        "_compute_trends": "report",
        "_compute_bottlenecks": "report",
        "_compute_all_time_stats": "report",
        "_compute_user_metrics": "report",
        "_compute_velocity_metrics": "report",
    },
    "ir.attachment": {
        "_unlink_approved_approval_request": "attachment",
        "_check_approval_requirement_belongs_to_the_request": "attachment",
    },
    "mail.activity": {
        "_get_answering_approvers": "activity",
    },
    "res.users": {
        "_approval_handover_on_archive": "crud",
    },
}


def _traced(target: Target, event: str, origin: Any, on_vals: bool = False) -> Any:
    @wraps(origin)
    def traced(self, *args: Any, **kwargs: Any) -> Any:
        if not target.on():
            return origin(self, *args, **kwargs)
        # `create` is called on an empty recordset, so its batch size is the
        # vals_list it was handed, not `self`.
        size = len(args[0]) if on_vals and args else len(self)
        cursor = self.env.cr
        before = getattr(cursor, "sql_log_count", 0)
        with target.span(event, n=size, uid=self.env.uid) as span:
            try:
                return origin(self, *args, **kwargs)
            finally:
                span["sql"] = getattr(cursor, "sql_log_count", 0) - before

    setattr(traced, TRACE_ORIGIN, origin)
    return traced


def instrument(model: models.BaseModel) -> None:
    """Wrap the entry points ``CALL_TRACES`` names on this model's class."""
    traced = CALL_TRACES.get(model._name)
    if not traced:
        return
    model_class = type(model)
    wrapped = []
    for method_name, target_name in traced.items():
        origin = getattr(model_class, method_name, None)
        if origin is None or getattr(origin, TRACE_ORIGIN, None) is not None:
            continue
        target = _BY_NAME[target_name]
        event = f"{model._name}.{method_name}"
        setattr(
            model_class,
            method_name,
            _traced(target, event, origin, on_vals=method_name == "create"),
        )
        wrapped.append(method_name)
    if wrapped:
        REGISTRY.event("instrumented", model=model._name, methods=len(wrapped))
    missing = [name for name in traced if not hasattr(model_class, name)]
    if missing:
        REGISTRY.note("stale_call_traces", model=model._name, methods=missing)


def uninstrument(model: models.BaseModel) -> None:
    """Undo :func:`instrument`, leaving anything else on the class alone."""
    if model._name not in CALL_TRACES:
        return
    model_class = type(model)
    for method_name in CALL_TRACES[model._name]:
        current = getattr(model_class, method_name, None)
        origin = getattr(current, TRACE_ORIGIN, None)
        if origin is None:
            continue
        if method_name in vars(model_class):
            delattr(model_class, method_name)
        if getattr(model_class, method_name, None) is not origin:
            setattr(model_class, method_name, origin)
