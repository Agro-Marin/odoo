from itertools import batched

from odoo import api, models
from odoo.tools import SQL


class IrModuleModule(models.Model):
    _inherit = "ir.module.module"

    @api.model
    def _load_module_terms(self, modules, langs, overwrite=False):

        super()._load_module_terms(modules, langs, overwrite=overwrite)

        to_langs = [lang for lang in langs if lang != "en_US"]
        if not (to_langs and modules):
            return

        def set_field(fname):
            lang_items = (
                SQL(
                    "%(lang)s, o_step.%(fname)s->>%(lang)s",
                    lang=SQL("'%s'" % lang),  # noqa: E8501  SQL literal, not a value
                    fname=fname,
                )
                for lang in to_langs
            )
            batched_lang_items = batched(lang_items, 50, strict=False)
            update_jsonb = SQL(" || ").join(
                SQL("jsonb_build_object(%s)", SQL(", ").join(batch))
                for batch in batched_lang_items
            )
            ordered = reversed if overwrite else iter
            src = SQL(" || ").join(
                ordered(
                    [
                        SQL("jsonb_strip_nulls(%s)", update_jsonb),
                        SQL("jsonb_strip_nulls(step.%s)", fname),
                    ]
                )
            )
            return SQL("%(fname)s = %(src)s", fname=fname, src=src)

        WebsiteCheckoutStep = self.env["website.checkout.step"]
        to_translate = [
            SQL.identifier(field.name)
            for field in WebsiteCheckoutStep._fields.values()
            if field.translate is True
        ]
        set_fields = SQL(", ").join(set_field(fname) for fname in to_translate)

        WebsiteCheckoutStep.invalidate_model()
        self.env.cr.execute(
            SQL(
                """
            UPDATE website_checkout_step step
               SET %(set_fields)s
              FROM website_checkout_step o_step
              JOIN website_checkout_step s_step
                ON o_step.step_href = s_step.step_href
             WHERE o_step.website_id IS NULL
               AND s_step.website_id IS NOT NULL
               AND step.id = s_step.id
            """,
                set_fields=set_fields,
            )
        )
