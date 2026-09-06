import hashlib
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

_RECOMPUTE_BATCH_SIZE = 200


class ResPartner(models.Model):
    _inherit = "res.partner"

    _SCORE_TRIGGERS = ()

    # Fields that can move a partner in or out of being the commercial entity.
    _COMMERCIAL_FIELDS = ("parent_id", "is_company", "type")

    attribute_line_ids = fields.One2many(
        comodel_name="res.partner.attribute.line",
        inverse_name="partner_id",
        string="Profile attributes",
    )
    score_points = fields.Float(
        compute="_compute_score",
        store=True,
        compute_sudo=True,
        precompute=True,
        help="Sum of the applied audit rows (see the score breakdown).",
    )
    score_max_possible = fields.Float(
        compute="_compute_score_max_possible",
        compute_sudo=True,
        help="Normalization denominator: the maximum points reachable "
        "across all active scoring dimensions with configured weights. A "
        "property of the catalog, read live rather than stored per partner.",
    )
    score_pct = fields.Float(
        string="Score (%)",
        compute="_compute_score",
        store=True,
        compute_sudo=True,
        precompute=True,
        help="Normalized score percentage (0-100) used to classify the "
        "partner into a commercial profile.",
    )
    date_last_score_update = fields.Datetime(
        string="Score Last Updated",
        readonly=True,
        help="When the score audit rows were last regenerated. A catalog "
        "weight change queues an async recompute (see "
        "_delay_profile_scores_recompute) -- this timestamp is how to tell "
        "the score is current versus still pending that background job.",
    )
    partner_profile_id = fields.Many2one(
        string="Commercial Profile",
        comodel_name="partner.profile",
        compute="_compute_partner_profile_id",
        store=True,
        compute_sudo=True,
        precompute=True,
        recursive=True,
        tracking=True,
        help="First active profile whose score range contains the partner's "
        "score percentage. A contact carries its commercial entity's profile: "
        "the score describes the customer, not the person. Tracked, so the "
        "chatter carries the band history. score_pct is deliberately not "
        "tracked: it moves on every catalog edit and every attribute capture, "
        "and would bury the transitions that carry commercial meaning.",
    )
    factor = fields.Float(
        string="Profile Factor",
        related="partner_profile_id.factor",
        readonly=True,
    )
    score_line_ids = fields.One2many(
        comodel_name="partner.score.line",
        inverse_name="partner_id",
        string="Score Breakdown",
    )
    score_line_count = fields.Count(
        "score_line_ids",
        string="Score Rows",
        store=True,
        help="How many audit rows explain the score. Stored so the partner "
        "form can decide whether to offer the breakdown without loading "
        "every row of it.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        if not self._SCORE_TRIGGERS:
            return partners
        to_score_ids = [
            partner.id
            for partner, vals in zip(partners, vals_list, strict=True)
            if any(field in vals for field in self._SCORE_TRIGGERS)
        ]
        if to_score_ids:
            self.browse(to_score_ids)._update_profile_scores()
        return partners

    def write(self, vals):
        result = super().write(vals)
        if any(field in vals for field in self._SCORE_TRIGGERS):
            self._update_profile_scores()
        if any(field in vals for field in self._COMMERCIAL_FIELDS):
            self._follow_commercial_partner()
        return result

    def _follow_commercial_partner(self):
        """Move captured attributes up when the contact hierarchy moves.

        _check_commercial_partner is an @api.constrains on the line's
        partner_id, and the ORM has no cross-model constrains: nothing re-runs
        it when the *partner* is demoted to a contact. The lines would keep
        scoring a record that is no longer the commercial entity while the new
        one scores as if nothing had ever been captured. Moving them is
        preferred over rejecting the move, which would block a legitimate
        hierarchy edit for a reason the user cannot act on.
        """
        line_model = self.env["res.partner.attribute.line"].with_context(
            active_test=False
        )
        for partner in self:
            commercial = partner.commercial_partner_id
            if commercial == partner:
                continue
            stray = line_model.search([("partner_id", "=", partner.id)])
            if not stray:
                continue
            taken = set(
                line_model.search([("partner_id", "=", commercial.id)]).attribute_id.ids
            )
            movable = stray.filtered(
                lambda line, taken=taken: line.attribute_id.id not in taken
            )
            if movable:
                movable.partner_id = commercial
            blocked = stray - movable
            if blocked:
                _logger.warning(
                    "partner_scoring: %s moved under %s but keeps %s captured "
                    "attribute(s) the commercial entity already answers: %s",
                    partner.display_name,
                    commercial.display_name,
                    len(blocked),
                    ", ".join(sorted(blocked.attribute_id.mapped("name"))),
                )

    @api.depends(
        "score_line_ids.points",
        "score_line_ids.applied",
    )
    def _compute_score(self):
        max_possible = self._get_score_max_possible()
        for partner in self:
            applied_rows = partner.score_line_ids.filtered("applied")
            partner.score_points = sum(applied_rows.mapped("points"))
            # Clamped: a stored row can outlive the weight that produced it
            # until the queued rescore lands, so a stale numerator degrades to
            # a capped score rather than a band above the scale.
            partner.score_pct = (
                min(partner.score_points / max_possible * 100.0, 100.0)
                if max_possible
                else 0.0
            )

    def _compute_score_max_possible(self):
        self.score_max_possible = self._get_score_max_possible()

    @api.depends(
        "score_pct",
        "company_id",
        "commercial_partner_id",
        "commercial_partner_id.partner_profile_id",
    )
    def _compute_partner_profile_id(self):
        profile_model = self.env["partner.profile"]
        scales = {}
        commercial = self.filtered(lambda p: p.commercial_partner_id == p)
        for partner in commercial:
            # The partner's own company, never the acting user's: this field is
            # stored and shared, so falling back to env.company would store
            # whichever scale the last user to trigger the compute happened to
            # be in. A company-less partner resolves against company-less bands.
            company = partner.company_id
            if company.id not in scales:
                scales[company.id] = profile_model.search(
                    [("active", "=", True)] + profile_model._scale_domain(company),
                    order="sequence, id",
                )
            partner.partner_profile_id = next(
                (
                    profile
                    for profile in scales[company.id]
                    if profile._covers(partner.score_pct)
                ),
                profile_model,
            )
        for partner in self - commercial:
            partner.partner_profile_id = (
                partner.commercial_partner_id.partner_profile_id
            )

    def action_partner_score_recompute(self):
        """Score inline for one partner, in the background for a selection.

        The action is bound to the partner list, where a user can select a
        whole page and run this in the request. Anything past a single record
        goes to the queue the module already owns for exactly this work.
        """
        if len(self) <= 1:
            self._update_profile_scores()
            return None
        self._delay_profile_scores_recompute()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "info",
                "title": self.env._("Scoring in the background"),
                "message": self.env._(
                    "%(count)s partners queued for recomputation.",
                    count=len(self),
                ),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    @api.model
    def _get_score_dimensions(self):
        return ["partner_attr"]

    @api.model
    def _get_score_ceiling_data(self):
        # Superuser and a fixed active_test, whatever the caller carries: the
        # ceiling is a property of the catalog, not of who asks. An archived
        # value is not reachable, so it is not in the ceiling.
        partner = self.env(su=True)["res.partner"].with_context(active_test=True)
        return {
            dimension: getattr(partner, f"_score_ceiling_{dimension}")()
            for dimension in self._get_score_dimensions()
        }

    @api.model
    def _get_score_max_possible(self):
        return sum(
            ceiling["total"] for ceiling in self._get_score_ceiling_data().values()
        )

    @api.model
    def _attribute_score_ceilings(self, attribute_model, domain):
        ceilings = []
        for attribute in self.env[attribute_model].search(domain):
            if attribute.aggregation_mode == "none":
                continue
            scores = [
                score
                for score in attribute.value_ids.mapped("score_value")
                if score > 0
            ]
            if not scores:
                continue
            summable = (
                attribute.value_type == "multi" and attribute.aggregation_mode == "sum"
            )
            ceilings.append((attribute.id, sum(scores) if summable else max(scores)))
        return {
            "model": attribute_model,
            "attributes": tuple(ceilings),
            "total": sum(ceiling for _attribute_id, ceiling in ceilings),
        }

    @api.model
    def _score_ceiling_partner_attr(self):
        return self._attribute_score_ceilings("res.partner.attribute", [])

    @api.job(channel="partner_scoring.recompute")
    def _update_profile_scores(self):
        env = self.env(su=True)
        ceilings = self._get_score_ceiling_data()
        dimensions = self._get_score_dimensions()

        rows = []
        for partner in self.with_env(env):
            for dimension in dimensions:
                rows += getattr(partner, f"_score_rows_{dimension}")(
                    ceilings[dimension]
                )
        self._reconcile_profile_score_rows(rows)
        for field_name in ("score_points", "score_pct", "partner_profile_id"):
            self.env.add_to_compute(self._fields[field_name], self)
        self.flush_recordset()
        # Raw SQL, deliberately: this is a bookkeeping stamp, not an edit of the
        # partner. Going through write() would move write_date on every catalog
        # recompute, so "when did this partner last change" would answer with a
        # background job instead of with the last real edit, and it would also
        # re-enter res.partner.write. The ORM cache is kept coherent by hand on
        # the line below.
        env.cr.execute(
            "UPDATE res_partner SET date_last_score_update = %s WHERE id = ANY(%s)",
            (fields.Datetime.now(), self.ids),
        )
        self.invalidate_recordset(["date_last_score_update"])

    @api.job(channel="partner_scoring.recompute")
    def _reclassify_profile_bands(self):
        """Re-run the classification only, leaving the audit rows alone."""
        self.env.add_to_compute(self._fields["partner_profile_id"], self)
        self.flush_recordset()

    @api.model
    def _notify_score_bands_changed(self):
        """Queue a reclassification after a change to the profile scale.

        Nothing depends on partner.profile itself, so an edited, archived or
        deleted band never reached the partners it governs and the stored
        classification drifted away from the configured scale. Cheaper than
        _notify_score_ceiling_changed: the audit rows and the percentage do
        not move, only the band the percentage falls into.

        Every partner, not only the scored or classified ones: a partner with
        no audit rows and no band is exactly the one a new band covering zero
        is meant to pick up.
        """
        if not self.env.registry.ready:
            return
        partners = (
            self.env(su=True)["res.partner"].with_context(active_test=False).search([])
        )
        for start in range(0, len(partners), _RECOMPUTE_BATCH_SIZE):
            batch = partners[start : start + _RECOMPUTE_BATCH_SIZE]
            batch.delayed(
                identity_key=batch._score_job_identity_key("reclassify")
            )._reclassify_profile_bands()

    def _score_job_identity_key(self, kind):
        """Deterministic key for a queued wave over exactly these partners.

        ir.job deduplicates queued jobs on identity_key, so a second wave over
        the same batch collapses onto the pending one instead of stacking. An
        admin tuning ten weights in one sitting otherwise queues ten complete
        recomputes of the whole customer base. Hashed over the ids rather than
        keyed on the batch bounds, so two different sets that happen to share
        their first and last partner do not collapse into one.
        """
        digest = hashlib.sha256(
            ",".join(str(partner_id) for partner_id in self.ids).encode()
        ).hexdigest()
        return f"partner_scoring.{kind}:{digest}"

    def _delay_profile_scores_recompute(self):
        for start in range(0, len(self), _RECOMPUTE_BATCH_SIZE):
            batch = self[start : start + _RECOMPUTE_BATCH_SIZE]
            batch.delayed(
                identity_key=batch._score_job_identity_key("recompute")
            )._update_profile_scores()

    @api.model
    def _notify_score_ceiling_changed(self):
        if not self.env.registry.ready:
            return
        # As superuser and without active_test: a catalog weight is shared, so
        # every partner carrying audit rows is stale, including the archived
        # ones and the ones the editing user's company rule hides.
        self.env(su=True)["res.partner"].with_context(active_test=False).search(
            [("score_line_ids", "!=", False)]
        )._delay_profile_scores_recompute()

    _SCORE_ROW_KEY = ("partner_id", "dimension", "source_key")
    _SCORE_ROW_VALUES = ("points", "max_points", "applied")

    def _reconcile_profile_score_rows(self, rows):
        score_model = self.env(su=True)["partner.score.line"]
        existing = score_model.search([("partner_id", "in", self.ids)])

        by_key = {}
        for row in existing:
            key = (row.partner_id.id, row.dimension, row.source_key)
            by_key.setdefault(key, []).append(row)

        to_create = []
        # Ids, not a recordset union: |= reallocates the whole id tuple on every
        # row, which is quadratic in the number of audit rows in the batch.
        matched_ids = set()
        for vals in rows:
            key = tuple(vals[name] for name in self._SCORE_ROW_KEY)
            candidates = by_key.get(key)
            if not candidates:
                to_create.append(vals)
                continue
            row = candidates.pop(0)
            matched_ids.add(row.id)
            changed = {
                name: vals[name]
                for name in self._SCORE_ROW_VALUES
                if row[name] != vals[name]
            }
            if changed:
                row.write(changed)

        stale = existing.filtered(lambda row: row.id not in matched_ids)
        if stale:
            stale.unlink()
        if to_create:
            score_model.create(to_create)

    def _score_rows_partner_attr(self, ceiling):
        self.check_singleton()
        return self._prepare_attribute_score_rows(
            "partner_attr", ceiling, self.attribute_line_ids
        )

    def _prepare_attribute_score_rows(self, dimension, ceiling, lines):
        self.check_singleton()
        attribute_model = self.env[ceiling["model"]]
        # Keyed by id and browsed in one go: the mapping depends only on the
        # ceiling argument, which is identical for every partner in the batch,
        # and browsing per attribute per partner defeats the prefetch.
        ceilings = dict(ceiling["attributes"])
        values_by_attribute = {}
        for line in lines:
            attribute_id = line.attribute_id.id
            values_by_attribute.setdefault(attribute_id, line.value_ids.browse())
            values_by_attribute[attribute_id] |= line.value_ids

        rows = []
        for attribute in attribute_model.browse(ceilings):
            attribute_ceiling = ceilings[attribute.id]
            values = values_by_attribute.get(attribute.id)
            if not values:
                rows.append(
                    self._prepare_score_row(
                        dimension=dimension,
                        source_key=f"{dimension}:{attribute.id}:none",
                        points=0.0,
                        max_points=attribute_ceiling,
                    )
                )
                continue
            best_value = max(values, key=lambda value: value.score_value)
            rows.extend(
                self._prepare_score_row(
                    dimension=dimension,
                    source_key=f"{dimension}:{attribute.id}:{value.id}",
                    points=value.score_value,
                    max_points=attribute_ceiling,
                    applied=attribute.aggregation_mode == "sum" or value == best_value,
                )
                for value in values
            )
        return rows

    def _prepare_score_row(
        self, dimension, source_key, points, max_points, applied=True
    ):
        self.check_singleton()
        return {
            "partner_id": self.id,
            "dimension": dimension,
            "source_key": source_key,
            "points": points,
            "max_points": max_points,
            "applied": applied,
        }

    @api.model
    def _score_labels_for_attribute_keys(self, attribute_model, value_model, keys):
        """Resolve 'dim:<attribute>:<value|none>' keys into reader-language labels.

        Archived records still label their rows: a row outlives the archive
        until the next refresh drops it, and a key is a worse label than the
        name of the thing it names.
        """
        parsed = {}
        for key in keys:
            _dimension, attribute_id, value_id = key.split(":")
            parsed[key] = (
                int(attribute_id),
                None if value_id == "none" else int(value_id),
            )
        attributes = self.env[attribute_model].sudo().with_context(active_test=False)
        values = self.env[value_model].sudo().with_context(active_test=False)
        attribute_names = {
            record.id: record.name
            for record in attributes.browse({a for a, _v in parsed.values()}).exists()
        }
        value_names = {
            record.id: record.name
            for record in values.browse(
                {v for _a, v in parsed.values() if v is not None}
            ).exists()
        }
        labels = {}
        for key, (attribute_id, value_id) in parsed.items():
            attribute_name = attribute_names.get(attribute_id)
            if attribute_name is None:
                continue
            if value_id is None:
                labels[key] = attribute_name
            elif value_id in value_names:
                labels[key] = f"{attribute_name}: {value_names[value_id]}"
        return labels

    @api.model
    def _score_labels_partner_attr(self, keys):
        return self._score_labels_for_attribute_keys(
            "res.partner.attribute", "res.partner.attribute.value", keys
        )

    @api.model
    def _score_row_note(self, dimension, source_key, applied):
        if not applied:
            return self.env._("Discarded: only the highest value counts.")
        if source_key.endswith(":none"):
            return self.env._("No data captured.")
        return ""
