# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models

from odoo.addons.base.models.res_lang import LangDataDict


class ResLang(models.Model):
    _inherit = "res.lang"

    def _get_frontend(self) -> LangDataDict:
        """Return the languages available on the frontend: every active one
        here, narrowed per website by the ``website`` override.

        :return: ``LangDataDict({code: LangData})``
        """
        return self._get_active_by("code")
