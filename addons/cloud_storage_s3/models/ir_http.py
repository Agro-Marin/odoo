from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    def session_info(self):
        res = super().session_info()
        attachment = self.env["ir.attachment"]
        if attachment._is_s3_provider() and (
            not attachment._s3_is_enabled() or attachment._is_s3_hybrid()
        ):
            res.pop("cloud_storage_min_file_size", None)
            res.pop("cloud_storage_unsupported_models", None)
        return res
