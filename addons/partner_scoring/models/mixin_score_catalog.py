from odoo import api, models


class MixinScoreCatalog(models.AbstractModel):
    _name = "mixin.score.catalog"
    _description = "Scored Catalog Mixin"

    # Field carrying the points a record is worth. It answers "did this record
    # contribute anything", which is the right question on create and unlink.
    _score_weight_field = None

    # Fields whose change can move a ceiling or rewrite a breakdown label. The
    # weight alone is not enough: archiving a weighted value, renaming it, or
    # re-homing it under another attribute each move something the score
    # depends on, and none of them touches the weight field. Left empty, the
    # mixin falls back to _score_weight_field, and treats every write as
    # relevant only when neither is set.
    _score_catalog_fields = ()

    def _has_score_weight(self):
        field_name = self._score_weight_field
        if not field_name:
            return bool(self)
        return any(record[field_name] for record in self)

    def _score_catalog_trigger_fields(self):
        """Names of the fields whose change invalidates the score catalog."""
        if self._score_catalog_fields:
            return self._score_catalog_fields
        if self._score_weight_field:
            return (self._score_weight_field,)
        return ()

    def _score_catalog_field_moved(self, record, field_name, value):
        current = record[field_name]
        if self._fields[field_name].type == "many2one":
            current = current.id
        return current != value

    def _score_catalog_changes(self, vals):
        watched = self._score_catalog_trigger_fields()
        if not watched:
            return bool(self)
        changed = [name for name in watched if name in vals]
        if not changed:
            return False
        return any(
            self._score_catalog_field_moved(record, name, vals[name])
            for record in self
            for name in changed
        )

    def _notify_score_catalog_changed(self):
        self.env["res.partner"]._notify_score_ceiling_changed()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        field_name = self._score_weight_field
        if field_name and any(vals.get(field_name) for vals in vals_list):
            records._notify_score_catalog_changed()
        return records

    def write(self, vals):
        moved = self._score_catalog_changes(vals)
        result = super().write(vals)
        if moved:
            self._notify_score_catalog_changed()
        if "name" in vals:
            self.env["partner.score.line"].invalidate_model(["source_ref"])
        return result

    def unlink(self):
        weighted = self._has_score_weight()
        result = super().unlink()
        if weighted:
            self._notify_score_catalog_changed()
        return result
