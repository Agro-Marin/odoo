"""Extraction as something a record has, rather than something a module does.

Any model that carries a document can inherit this and get the whole pipeline:
a state, a result with its provenance, the fields nobody could read, and both a
synchronous and a queued way to run it. A consumer declares two things -- which
schema its documents follow, and which of its own fields the schema's fields
land in -- and overrides one hook when its filling is more than a mapping.

The arrangement it replaces is worth naming, because it is what a framework
looks like before it has a registry. Odoo's ``extract.mixin`` welds three
unrelated things together: one backend (IAP, with its credits, its document
uuid and its webhook), per-consumer glue that each module reimplements, and an
asynchrony hand-rolled from a state field, a status field and a polling cron.
Here the backend is whichever strategies are registered, the glue is two class
attributes and a hook, and the asynchrony is ``ir.job``.

``partial`` is a state, not an error. A document that yields nine required
fields of eleven is more useful than an exception, and the two it did not yield
are named in ``extract_missing`` so a person can be pointed at exactly them.
Refusing the nine is how a system teaches people to stop using it.
"""

from __future__ import annotations

import logging
from typing import Any

from odoo import api, fields, models

from ..tools import GENERATIVE, cascade
from ..tools.schema import known_schemas
from ..tools.source import DocumentSource

_logger = logging.getLogger(__name__)

JOB_CHANNEL = "document_extract"

# How long to leave a service alone before asking it again, and how many times.
# Odoo's own extraction answers in seconds to minutes; a document still unread
# after this many attempts is a document something is wrong with, and saying so
# is more useful than asking forever.
WAIT_SECONDS = 30
WAIT_ATTEMPTS = 40

STATES = [
    ("none", "Not extracted"),
    ("queued", "Queued"),
    ("running", "Running"),
    ("waiting", "Waiting on a service"),
    ("done", "Extracted"),
    ("partial", "Partially extracted"),
    ("failed", "Failed"),
]


class MixinDocumentExtract(models.AbstractModel):
    _name = "mixin.document.extract"
    _description = "Document Extraction"

    # Which schema this model's documents follow. A model whose documents vary
    # overrides ``_get_extract_document_type`` and answers per record instead.
    _extract_document_type: str = ""

    # Schema field -> field on this model, for the values that are a plain
    # mapping. Anything conditional belongs in ``_update_from_extraction``.
    _extract_target: dict[str, str] = {}

    extract_state = fields.Selection(
        STATES, default="none", readonly=True, copy=False, index=True
    )
    extract_result = fields.Json(
        readonly=True,
        copy=False,
        help="Every value that was read, with which strategy proposed it and "
        "how confident it was.",
    )
    extract_missing = fields.Json(
        readonly=True,
        copy=False,
        help="Required fields no strategy could read, and rules that do not "
        "hold. What a person has to supply.",
    )
    extract_error = fields.Text(readonly=True, copy=False)
    extract_pending = fields.Json(
        readonly=True,
        copy=False,
        help="The service this document is waiting on, and its handle. Kept so "
        "the next attempt asks again rather than submitting the document a "
        "second time.",
    )
    extract_corrections = fields.Json(
        readonly=True,
        copy=False,
        help="Fields a person changed after extraction, with what was read and "
        "what it should have been.",
    )

    # -- what a consumer declares ------------------------------------

    def _get_extract_document_type(self) -> str:
        """Which schema this record's document follows."""
        return self._extract_document_type

    def _get_extract_source(self) -> DocumentSource | None:
        """The document to read.

        Defaults to the record's main attachment where the model tracks one,
        and otherwise to its most recent attachment. A model that keeps its
        document somewhere else overrides this; the framework never guesses at
        a field name.
        """
        self.ensure_one()
        attachment = None
        if "message_main_attachment_id" in self._fields:
            attachment = self.message_main_attachment_id
        if not attachment:
            attachment = self.env["ir.attachment"].search(
                [("res_model", "=", self._name), ("res_id", "=", self.id)],
                order="id desc",
                limit=1,
            )
        if not attachment or not attachment.raw:
            return None
        return DocumentSource.of(attachment)

    def _update_from_extraction(self, result) -> None:
        """Put what was read onto the record.

        The base applies ``_extract_target`` and nothing else. Override to add
        what a mapping cannot express -- predicting a product from a
        description, preferring a catalogue price over the printed one,
        resolving a partner. That logic is not plumbing and does not disappear;
        it moves here, where it is named.
        """
        self.ensure_one()
        values = {}
        for schema_field, model_field in self._extract_target.items():
            if model_field not in self._fields:
                _logger.warning(
                    "%s maps %r to %r, which is not a field of this model",
                    self._name,
                    schema_field,
                    model_field,
                )
                continue
            value = result.flat().get(schema_field)
            if value is not None and not self[model_field]:
                values[model_field] = value
        if values:
            self.write(values)

    # -- running it ---------------------------------------------------

    def action_extract(self):
        """Read the document now, spending whatever it takes."""
        for record in self:
            record._extract_document(up_to=GENERATIVE)
        return True

    def action_extract_later(self):
        """Queue the reading, and return while it happens."""
        for record in self:
            record._extract_later()
        return True

    def _extract_later(self, delay: int = 0):
        """Put this record's document on the queue.

        ``identity_key`` makes it idempotent: a sweep that runs every hour
        cannot collect a second job for a document already waiting for one.
        """
        self.ensure_one()
        job = self.delayed(
            channel=JOB_CHANNEL,
            eta=delay or None,
            identity_key=f"document_extract.{self._name}.{self.id}",
            description=f"Extract {self._get_extract_document_type()}: "
            f"{self.display_name}",
        )._job_extract()
        self.extract_state = "queued"
        return job

    @api.job(channel=JOB_CHANNEL, max_retries=3, max_defers=WAIT_ATTEMPTS)
    def _job_extract(self) -> None:
        """The queued reading, which is also the only one that may wait.

        Its own transaction, so a slow service holds nothing open, and its own
        retries. Nothing is passed in: job arguments must be serializable and a
        document source is not, so the source is derived here from the record.

        A strategy that answers later leaves the result waiting, and this job
        defers rather than failing. A deferral is not a failure and has its own
        budget: a service that takes ten minutes must not consume the tolerance
        that exists for genuine errors.
        """
        self.ensure_one()
        result = self._extract_document(up_to=GENERATIVE, allow_pending=True)
        if result is not None and result.waiting:
            self.env["ir.job"]._defer(
                WAIT_SECONDS,
                reason=f"{result.pending['strategy']} is still reading the document.",
            )

    def _extract_document(self, up_to: int = GENERATIVE, allow_pending: bool = False):
        """Read the document and record what came back, whatever that is."""
        self.ensure_one()
        doc_type = self._get_extract_document_type()
        if not doc_type:
            raise ValueError(
                f"{self._name} inherits mixin.document.extract without "
                "declaring _extract_document_type"
            )
        if doc_type not in known_schemas():
            raise ValueError(
                f"{self._name} declares document type {doc_type!r}, which no "
                f"module registers; known: {', '.join(known_schemas())}"
            )

        source = self._get_extract_source()
        if source is not None and allow_pending:
            # A queued reading can afford to make text out of a scan; a
            # synchronous one cannot, and sees a document with no text rather
            # than waiting on an engine inside somebody's transaction.
            source.allow_ocr = True
        if source is None:
            self.write(
                {
                    "extract_state": "failed",
                    "extract_error": "No document to read.",
                }
            )
            return None

        self.extract_state = "running"
        try:
            result = cascade.run(
                source,
                doc_type,
                env=self.env,
                up_to=up_to,
                allow_pending=allow_pending,
                pending=self.extract_pending or None,
            )
        except Exception as e:
            _logger.exception("Extraction failed on %s %s", self._name, self.id)
            self.write({"extract_state": "failed", "extract_error": str(e)})
            return None

        if result.waiting:
            self.write({"extract_state": "waiting", "extract_pending": result.pending})
            return result

        self.write(
            {
                "extract_pending": False,
                "extract_state": "done" if result.satisfied else "partial",
                "extract_result": _as_json(result),
                "extract_missing": {
                    "fields": list(result.missing),
                    "rules": list(result.violations),
                },
                "extract_error": False,
            }
        )
        self._update_from_extraction(result)
        return result

    # -- learning from being corrected --------------------------------

    def write(self, vals):
        """Record a person disagreeing with what was read.

        The most valuable data this system produces, and the thing Odoo's
        extraction throws away: a field someone changed after extraction is a
        labelled example of the reader being wrong. Kept per field with what
        was read and which strategy read it, so a strategy that is reliably
        wrong about one field can be found rather than suspected.
        """
        # ir.attachment inherits this, and attachments are written constantly.
        # Everything below is skipped unless the model actually maps a schema
        # field onto one of its own and the write touches it, so the override
        # costs a dict lookup on the paths that have nothing to do with
        # extraction.
        watched = set(self._extract_target.values()) & set(vals)
        corrections = {}
        if watched and not self.env.context.get("extracting"):
            for record in self:
                found = record._corrections_in(vals)
                if found:
                    corrections[record.id] = found

        result = super().write(vals)

        for record in self:
            found = corrections.get(record.id)
            if found:
                stored = dict(record.extract_corrections or {})
                stored.update(found)
                super(MixinDocumentExtract, record.with_context(extracting=True)).write(
                    {"extract_corrections": stored}
                )
        return result

    def _corrections_in(self, vals: dict[str, Any]) -> dict[str, Any]:
        self.ensure_one()
        if not self.extract_result or not self._extract_target:
            return {}
        found = {}
        for schema_field, model_field in self._extract_target.items():
            if model_field not in vals:
                continue
            read = (self.extract_result or {}).get(schema_field)
            if not read or read.get("value") in (None, vals[model_field]):
                continue
            found[schema_field] = {
                "read": read.get("value"),
                "read_by": read.get("source"),
                "corrected_to": vals[model_field],
            }
        return found


def _as_json(result) -> dict[str, Any]:
    """The envelope, flattened enough to live in a Json column."""
    return {
        name: {
            "value": field.value,
            "source": field.source,
            "confidence": field.confidence,
            "disputed": field.disputed,
            "candidates": [
                {"value": c.value, "source": c.source, "confidence": c.confidence}
                for c in field.candidates
            ],
        }
        for name, field in result.fields.items()
    }
