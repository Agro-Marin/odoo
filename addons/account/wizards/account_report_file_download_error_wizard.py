from odoo import fields, models

from ..tools import debug_log as dbg


class AccountReportFileDownloadErrorWizard(models.TransientModel):
    _name = "account.report.file.download.error.wizard"
    _description = "Manage the file generation errors from report exports."

    actionable_errors = fields.Json()
    file_name = fields.Char()
    file_content = fields.Binary()

    @dbg.timed
    def button_download(self):
        dbg.lifecycle.debug("button_download on %s", dbg.rec(self))
        self.check_singleton()
        if self.file_name:
            return {
                "type": "ir.actions.act_url",
                "url": f"/web/content/account.report.file.download.error.wizard/{self.id}/file_content/{self.file_name}?download=1",
                "close": True,
            }
        return None
