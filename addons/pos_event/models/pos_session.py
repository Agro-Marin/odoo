from odoo import api, models


class PosSession(models.Model):
    _inherit = 'pos.session'

    @api.model
    def _get_model_names_to_load(self, config):
        models = super()._get_model_names_to_load(config)
        models += ['event.event.ticket', 'event.event', 'event.slot', 'event.registration', 'event.question', 'event.question.answer', 'event.registration.answer']
        return models

    @api.model
    def _get_field_relations(self, model, fields):
        relations = super()._get_field_relations(model, fields)
        if model == 'event.registration':
            # Force compute to False otherwise the frontend will not send the data
            relations['email']['compute'] = False
            relations['phone']['compute'] = False
            relations['name']['compute'] = False
            relations['company_name']['compute'] = False
            relations['event_slot_id']['compute'] = False
        return relations
