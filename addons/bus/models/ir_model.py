from odoo import models


class IrModel(models.Model):
    _inherit = "ir.model"

    def _get_model_definitions(self, model_names_to_fetch):
        # Model-level ACL: silently omit models the current user cannot read.
        # Without this, any authenticated user (including portal) could
        # enumerate the schema of arbitrary models.  Omitting (rather than
        # erroring) keeps batch requests from the web client working when a
        # subset of the requested models is restricted.
        # Deduplicate while keeping order: the payload is client-controlled and
        # a repeated name used to redo the whole ``fields_get`` + inverse-field
        # pass for an entry that overwrites itself in the result dict.
        model_names_to_fetch = [
            model_name
            for model_name in dict.fromkeys(model_names_to_fetch)
            if self.env[model_name].has_access("read")
        ]
        # Set, not the list: this is used as a membership test once per field
        # of every fetched model.
        fetched_model_names = set(model_names_to_fetch)
        model_definitions = {}
        for model_name in model_names_to_fetch:
            model = self.env[model_name]
            # get fields, relational fields are kept only if the related model is in model_names_to_fetch
            fields_data_by_fname = {
                fname: field_data
                for fname, field_data in model.fields_get(
                    attributes={
                        "name",
                        "type",
                        "relation",
                        "required",
                        "readonly",
                        "selection",
                        "string",
                        "definition_record",
                        "definition_record_field",
                        "model_field",
                    },
                ).items()
                if not field_data.get("relation")
                or field_data["relation"] in fetched_model_names
            }
            for fname, field_data in fields_data_by_fname.items():
                if fname in model._fields:
                    inverse_fields = [
                        field
                        for field in model.pool.field_inverses[model._fields[fname]]
                        if field.model_name in fetched_model_names
                        and model.env[field.model_name]._has_field_access(field, "read")
                    ]
                    if inverse_fields:
                        field_data["inverse_fname_by_model_name"] = {
                            field.model_name: field.name for field in inverse_fields
                        }
                    if field_data["type"] == "many2one_reference":
                        field_data["model_name_ref_fname"] = model._fields[
                            fname
                        ].model_field
            model_definitions[model_name] = {"fields": fields_data_by_fname}
        return model_definitions
