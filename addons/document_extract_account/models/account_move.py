from __future__ import annotations

import logging

from odoo import api, fields, models
from odoo.exceptions import LockError, UserError
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)

# How many partners carrying one tax identifier we are prepared to look at
# before giving up. A company plus its contacts is a handful; hundreds means
# the identifier is not identifying anything.
CANDIDATE_LIMIT = 50


class AccountMove(models.Model):
    _name = "account.move"
    _inherit = ["account.move", "mixin.document.extract"]

    _extract_document_type = "invoice"

    _extract_target = {
        "invoice_date": "invoice_date",
        "invoice_number": "ref",
    }

    extract_can_be_read = fields.Boolean(compute="_compute_extract_can_be_read")
    extract_has_lines = fields.Boolean(compute="_compute_extract_has_lines")
    extract_lines_applied = fields.Boolean(
        readonly=True,
        copy=False,
        help="Whether the lines read from the document have already been added "
        "to this bill. Kept so the screen that offers them cannot add them "
        "a second time.",
    )

    @api.depends("state", "move_type", "extract_state")
    def _compute_extract_can_be_read(self) -> None:
        for move in self:
            move.extract_can_be_read = (
                move.state == "draft"
                and move.is_purchase_document()
                and move.extract_state in ("none", "failed", "partial")
            )

    @api.depends("extract_result", "state", "extract_lines_applied")
    def _compute_extract_has_lines(self) -> None:
        for move in self:
            read = move._extract_read_lines()
            move.extract_has_lines = (
                bool(read.get("value"))
                and move.state == "draft"
                and not move.extract_lines_applied
            )

    def _extract_read_lines(self) -> dict:
        """The ``lines`` entry of what was read: value, source and confidence.

        Deliberately no ``ensure_one()``: ``_compute_extract_has_lines`` calls
        this per record inside its loop, and the envelope is per record anyway.
        """
        return (self.extract_result or {}).get("lines") or {}

    def _get_extract_document_type(self) -> str:
        self.ensure_one()
        # "" is the sentinel for "this record has no document to read", and
        # documents_l10n_mx_edi's override calls super() and depends on both it
        # and the declared type. Neither may be replaced with a literal.
        return self._extract_document_type if self.is_purchase_document() else ""

    def _update_from_extraction(self, result) -> None:
        self.ensure_one()
        super()._update_from_extraction(result)

        values = result.flat()
        writes = {}

        if not self.partner_id:
            partner = self._get_extract_partner(values.get("vendor_vat"))
            if partner:
                writes["partner_id"] = partner.id

        currency = self._get_extract_currency(values.get("currency"))
        if (
            currency
            and currency != self.currency_id
            and self._extract_may_set_currency()
        ):
            writes["currency_id"] = currency.id

        if self.extract_lines_applied:
            # A fresh reading produces fresh lines, which nobody has accepted yet.
            writes["extract_lines_applied"] = False

        if writes:
            self.write(writes)

        # After the supplier is on the record, never before: a payment term
        # usually arrives with the supplier, and consulting the term first let
        # a date printed on the document silently outrank an agreed one.
        if values.get("due_date") and not self.invoice_payment_term_id:
            self.invoice_date_due = values["due_date"]

        lines = values.get("lines")
        if lines:
            _logger.info(
                "Read %d line(s) from the document on %s; they are recorded in "
                "extract_result and not posted, because a line decides an "
                "account and a tax",
                len(lines),
                self.name or self.id,
            )

    def _get_extract_partner(self, vat: str | None):
        if not vat:
            return None
        candidates = self.env["res.partner"].search(
            [
                ("vat", "=ilike", vat.strip()),
                ("company_id", "in", (False, self.company_id.id)),
            ],
            limit=CANDIDATE_LIMIT,
        )
        if len(candidates) == CANDIDATE_LIMIT:
            # More records than we are willing to look at. Refusing is the only
            # honest answer: the cap may have hidden a second company.
            _logger.info(
                "More than %s partners carry the tax identifier %r; none chosen",
                CANDIDATE_LIMIT,
                vat,
            )
            return None

        # A company and its own contacts are one supplier, not several. The
        # tax identifier is a commercial field, so res.partner copies it from a
        # parent onto every child; counting the raw matches would reject every
        # vendor that has an address or a person attached to it.
        companies = candidates.commercial_partner_id
        if len(companies) != 1:
            if companies:
                _logger.info(
                    "%s distinct partners share the tax identifier %r; none chosen",
                    len(companies),
                    vat,
                )
            return None
        return companies

    def _extract_may_set_currency(self) -> bool:
        """Whether the currency on this bill is still the one nobody chose.

        A currency is never empty, so "written only into emptiness" cannot mean
        a falsy field here. It means the bill still carries the default it was
        created with and nothing has been priced in it yet. A bill whose
        currency a person changed is left alone, at the cost of not being able
        to tell that choice from a deliberate re-pick of the default -- which
        is the safe way round.
        """
        self.ensure_one()
        default = self.journal_id.currency_id or self.company_id.currency_id
        return self.currency_id == default and not self.invoice_line_ids

    def _get_extract_currency(self, name: str | None):
        if not name:
            return None
        # Archived currencies are excluded deliberately: writing one sets
        # `display_inactive_currency_warning`, and account.view_move_form hides
        # the Confirm button when it is set, so reading a document would leave
        # a bill nobody can post.
        return self.env["res.currency"].search(
            [("name", "=", name.strip().upper())], limit=1
        )

    @api.model
    def _extract_line_seed(self, line: dict) -> dict:
        """What the review screen offers for one line the document stated.

        Used both to fill that screen and, afterwards, to decide whether a
        person changed anything -- so a value this module invented for display
        can never come back as somebody's correction. `is None` rather than
        falsiness, because a document that states a quantity of zero is stating
        something, and turning it into one would invent a line item.
        """
        described = line.get("description")
        quantity = line.get("quantity")
        price = line.get("unit_price")
        return {
            "description": described or self.env._("Unnamed line"),
            "quantity": 1.0 if quantity is None else quantity,
            "price_unit": 0.0 if price is None else price,
        }

    @api.model
    def _extract_line_differs(self, proposal, seed: dict) -> bool:
        """Whether a person actually changed the line the screen offered them.

        The numbers are compared at the precision the fields can hold. A
        document stating a unit price finer than the field stores it comes back
        rounded, and that rounding is this module's doing, not a person's
        disagreement.
        """
        currency = proposal.currency_id or self.currency_id
        if currency.compare_amounts(proposal.price_unit, seed["price_unit"]):
            return True
        digits = proposal._fields["quantity"].get_digits(self.env)
        precision = digits[1] if digits else 2
        if float_compare(
            proposal.quantity, seed["quantity"], precision_digits=precision
        ):
            return True
        return proposal.description != seed["description"]

    def action_review_extracted_lines(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError(
                self.env._("Only a draft bill can take lines read from its document.")
            )
        lines = self._extract_read_lines().get("value") or []
        if not lines:
            raise UserError(self.env._("No lines were read from this bill's document."))

        wizard = self.env["account.move.extract.line.wizard"].create(
            self.env["account.move.extract.line.wizard"]._prepare_from_move(self)
        )
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Lines read from the document"),
            "res_model": "account.move.extract.line.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }

    def _add_extraction_correction_for_lines(self, proposals) -> None:
        self.ensure_one()
        read = self._extract_read_lines().get("value") or []
        changed = []
        for proposal in proposals:
            # By index, never by position: the review list can be reordered with
            # the handle widget, and pairing the two sequences positionally
            # would file a person's edit against somebody else's line.
            if not 0 <= proposal.read_index < len(read):
                continue
            original = read[proposal.read_index]
            if not proposal.accepted:
                changed.append({"read": original, "corrected_to": None})
                continue
            if self._extract_line_differs(proposal, self._extract_line_seed(original)):
                changed.append(
                    {
                        "read": original,
                        "corrected_to": {
                            "description": proposal.description,
                            "quantity": proposal.quantity,
                            "unit_price": proposal.price_unit,
                        },
                    }
                )
        if not changed:
            return
        source = self._extract_read_lines().get("source")
        stored = dict(self.extract_corrections or {})
        # Accumulate. Reading the document again offers its lines again, and a
        # person may disagree a second time; assigning the key would throw away
        # what they told us on the first pass. Each change carries the reader it
        # disagreed with, because two passes can come from two strategies.
        previous = (stored.get("lines") or {}).get("changes") or []
        stored["lines"] = {
            "read_by": source,
            "changes": [*previous, *({**c, "read_by": source} for c in changed)],
        }
        self.with_context(extracting=True).write({"extract_corrections": stored})

    def action_extract_document(self):
        self.ensure_one()
        if not self._get_extract_document_type():
            raise UserError(
                self.env._(
                    "Only a vendor bill carries a document this can read. "
                    "%(name)s is not one.",
                    name=self.display_name,
                )
            )
        # One reader at a time. The mixin's early `extract_state = "running"` is
        # an ORM cache assignment flushed at commit, so it takes no lock and two
        # clicks ran the whole cascade twice -- and the cascade reaches
        # generative strategies, so twice meant paying twice. Taking the lock
        # here makes the second caller wait before it spends anything.
        try:
            self.lock_for_update()
        except LockError as error:
            raise UserError(
                self.env._(
                    "This bill's document is already being read. Try again in a moment."
                )
            ) from error
        result = self._extract_document()
        if result is None:
            return False
        if result.satisfied:
            message = self.env._("The document was read in full.")
        else:
            message = self.env._(
                "The document was read in part. Still missing: %(fields)s",
                fields=", ".join(result.missing) or self.env._("nothing required"),
            )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"message": message, "type": "info", "sticky": False},
        }
