import json

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..tools import s3_drive


class CloudDriveConfig(models.TransientModel):
    _name = "cloud.drive.config"
    _description = "Cloud Drive Configuration"

    bucket_name = fields.Char()
    region = fields.Char(help="AWS region of the Drive bucket, e.g. us-east-2.")
    access_key_id = fields.Char(string="Access Key ID")
    secret_access_key = fields.Char()
    keys_set = fields.Boolean(
        string="Credentials stored",
        readonly=True,
        help="Whether readable IAM keys are already stored in the credential vault.",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        icp = self.env["ir.config_parameter"].sudo()
        res["bucket_name"] = icp.get_param(s3_drive.PARAM_BUCKET) or False
        res["region"] = icp.get_param(s3_drive.PARAM_REGION) or False
        credential = s3_drive._get_credential(self.env)
        res["keys_set"] = bool(credential) and credential.storage_method == "json"
        return res

    def _store_keys(self, payload):
        credential = s3_drive._get_credential(self.env)
        if credential:
            credential.credential_data = payload
            return
        category = self.env.ref(s3_drive.CREDENTIAL_CATEGORY_XMLID)
        self.env["credential.credential"].sudo().create(
            {
                "name": "Cloud Drive S3",
                "category_id": category.id,
                "credential_data": payload,
            }
        )

    def _persist(self):
        self.check_singleton()
        if bool(self.access_key_id) != bool(self.secret_access_key):
            raise UserError(
                self.env._(
                    "Provide both the Access Key ID and the Secret Access Key, "
                    "or leave both empty to keep the stored keys."
                )
            )
        icp = self.env["ir.config_parameter"].sudo()
        icp.set_param(s3_drive.PARAM_BUCKET, self.bucket_name or "")
        icp.set_param(s3_drive.PARAM_REGION, self.region or "")
        if self.access_key_id and self.secret_access_key:
            self._store_keys(
                json.dumps(
                    {
                        "access_key_id": self.access_key_id,
                        "secret_access_key": self.secret_access_key,
                    }
                )
            )
            self.write({"access_key_id": False, "secret_access_key": False})
            self.keys_set = True
        s3_drive.clear_cache(self.env)

    def action_save(self):
        self._persist()
        return {"type": "ir.actions.act_window_close"}

    def action_test_connection(self):
        self._persist()
        bucket = s3_drive.test_connection(self.env)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": self.env._("Connection OK"),
                "message": self.env._("Reached bucket '%s' successfully.", bucket),
                "sticky": False,
            },
        }
