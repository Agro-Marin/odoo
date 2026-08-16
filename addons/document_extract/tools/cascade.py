"""Spend the cheapest strategy that can answer, and stop when the answer holds.

This generalizes the layered ladder several modules grew independently -- try
the structured source, then a template, then an OCR service -- with two
differences that came out of measuring the existing one.

It stops on *satisfaction*, not on a strategy having returned something. A
parser that returns a dict has not necessarily read the document: measured on a
real utility bill, a reworded label dropped the subtotal, tax, surcharge and
total together while twenty-eight other fields came back intact and the parser
reported success. Satisfaction is the schema's business -- required fields
present, consistency rules holding -- and it is checked after every strategy.

And it escalates per field rather than per document. The nine fields a free
strategy read are kept; only what is missing or contradictory is asked of the
next one, which is where the cost is.

Some strategies answer later
----------------------------
A service that accepts a document and prepares an answer over seconds or
minutes cannot be expressed as a function that returns one. Such a strategy
implements ``submit`` and ``poll`` instead of ``extract``, and the cascade
reaches it only when the caller says it can wait -- which in practice means the
background queue, where waiting is a deferral rather than a held transaction.

A synchronous caller skips them exactly as it skips a strategy whose ``needs``
the document cannot provide: not an error, just not applicable here.
"""

from __future__ import annotations

import logging

from .candidates import ExtractionResult
from .extractors import GENERATIVE, PENDING, get_extractors
from .schema import get_schema
from .source import DocumentSource

_logger = logging.getLogger(__name__)


def run(
    source: DocumentSource,
    doc_type: str,
    env=None,
    up_to: int = GENERATIVE,
    allow_pending: bool = False,
    pending: dict | None = None,
) -> ExtractionResult:
    """Extract ``doc_type`` from ``source``, spending no more than ``up_to``.

    :param source: the document, in whatever format it arrived
    :param doc_type: a registered schema name
    :param env: the Odoo environment, for strategies that reach a service
    :param up_to: the most expensive strategy that may run. ``FREE`` is what a
        posting path wants: structured strategies only, no network, no meter.
    :param allow_pending: whether the caller can be handed an unfinished result
        and come back for it. Only a queued caller can.
    :param pending: what a previous call was waiting on, asked again before
        anything else is tried.
    :return: an :class:`ExtractionResult`, always -- an unsatisfied one reports
        what is missing rather than raising, because a document that yields
        nine fields of eleven is worth more than an exception.
    """
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
    """Ask again for an answer a previous call is still waiting on.

    Returns False when the answer is still not ready, which leaves ``result``
    waiting and ends the run: nothing cheaper is worth trying, because
    everything cheaper was already tried before the service was asked.
    """
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
    """Hand the document to a service. True when we are now waiting on it."""
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
    """Fields the next strategy should spend its budget on."""
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
    """Run one strategy, treating its failure as "no answer".

    A strategy that raises must not take the document with it: the next one may
    well read it, and a caller holding a partial result is better off than one
    holding a traceback. The failure is logged with the strategy named, so a
    silent one cannot masquerade as a document that had nothing to give.
    """
    try:
        return extractor.extract(source, doc_type, wanted, env=env)
    except Exception:
        _logger.exception(
            "Extractor %r failed on %r; continuing with the next strategy",
            extractor.name,
            source.name or source.mimetype,
        )
        return None
