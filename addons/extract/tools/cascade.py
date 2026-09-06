from __future__ import annotations

import logging

from odoo.libs.documents import Document

from .candidates import ExtractionResult
from .extractors import GENERATIVE, PENDING, get_extractors
from .schema import get_schema

_logger = logging.getLogger(__name__)


def run(
    source: Document,
    doc_type: str,
    env=None,
    up_to: int = GENERATIVE,
    allow_pending: bool = False,
    pending: dict | None = None,
) -> ExtractionResult:
    schema = get_schema(doc_type)
    result = ExtractionResult(schema)

    if pending and not _resume(result, pending, allow_pending, env):
        return result

    for extractor in get_extractors(source, doc_type, up_to):
        if extractor.name in result.ran:
            continue

        wanted = _wanted(result)
        if _is_two_phase(extractor):
            if not allow_pending:
                _logger.debug(
                    "%s answers later and this caller cannot wait; skipped",
                    extractor.name,
                )
                continue
            if _submit(result, extractor, source, doc_type, wanted, env):
                return result
            continue

        values = _run_one(extractor, source, doc_type, wanted, env)
        result.ran.append(extractor.name)
        if not values:
            continue

        for name, value in values.items():
            result.add(name, value, extractor.name, extractor.confidence)

        if result.satisfied:
            _logger.info("%s satisfied by %s", doc_type, " -> ".join(result.ran))
            return result

    if result.missing or result.violations:
        _logger.info(
            "%s incomplete after %s: missing %s, violating %s",
            doc_type,
            " -> ".join(result.ran) or "no applicable strategy",
            list(result.missing),
            list(result.violations),
        )
    return result


def _is_two_phase(extractor) -> bool:
    return hasattr(extractor, "submit") and hasattr(extractor, "poll")


def _resume(result, pending: dict, allow_pending: bool, env) -> bool:
    name = pending.get("strategy")
    extractor = next((e for e in get_extractors() if e.name == name), None)
    if extractor is None or not _is_two_phase(extractor):
        _logger.warning(
            "Waiting on %r, which is no longer a strategy that answers later; "
            "reading the document again from the beginning",
            name,
        )
        return True

    try:
        answer = extractor.poll(pending.get("handle"), env=env)
    except Exception:
        _logger.exception("%s failed while being asked again", name)
        result.ran.append(name)
        return True

    if answer is PENDING:
        if allow_pending:
            result.pending = pending
            return False
        _logger.info("%s is still working, and this caller cannot wait", name)
        return True

    result.ran.append(name)
    for field, value in (answer or {}).items():
        result.add(field, value, name, extractor.confidence)
    return True


def _submit(result, extractor, source, doc_type, wanted, env) -> bool:
    try:
        handle = extractor.submit(source, doc_type, wanted, env=env)
    except Exception:
        _logger.exception("%s would not accept the document", extractor.name)
        result.ran.append(extractor.name)
        return False

    if not handle:
        result.ran.append(extractor.name)
        return False

    result.pending = {"strategy": extractor.name, "handle": handle}
    _logger.info("%s accepted the document; waiting for its answer", extractor.name)
    return True


def _wanted(result: ExtractionResult) -> tuple[str, ...]:
    if not result.ran:
        return tuple(result.schema.fields)
    rule_fields = {
        name
        for rule in result.schema.rules
        if rule.name in result.violations
        for name in rule.fields
    }
    return tuple(dict.fromkeys((*result.missing, *sorted(rule_fields))))


def _run_one(extractor, source, doc_type, wanted, env):
    try:
        return extractor.extract(source, doc_type, wanted, env=env)
    except Exception:
        _logger.exception(
            "Extractor %r failed on %r; continuing with the next strategy",
            extractor.name,
            source.name or source.mimetype,
        )
        return None
