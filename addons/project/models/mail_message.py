from odoo import models


class MailMessage(models.Model):
    _inherit = "mail.message"

    _res_id_id_date_for_burndown_chart = models.Index(
        "(res_id, id, date) WHERE model = 'project.task' AND message_type = 'notification'"
    )
