from odoo import models


class CalendarEventType(models.Model):
    _name = 'calendar.event.type'
    _description = 'Event Meeting Type'
    # `name`, `active`, `color` and `code` come from the mixin, flat: meeting
    # types do not nest. `name` becomes translatable in the process, which is
    # why the old `unique (name)` goes -- over a jsonb column it compares whole
    # translation documents and enforces nothing once a second language is
    # active. The mixin indexes the source term instead, and identity moves to
    # `code`.
    _inherit = ['mixin.tag']
