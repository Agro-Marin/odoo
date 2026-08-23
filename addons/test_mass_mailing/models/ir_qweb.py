from odoo import models


class IrQweb(models.AbstractModel):
    _inherit = "ir.qweb"

    def _get_bundles_to_pregenerate(self):
        js_assets, css_assets = super()._get_bundles_to_pregenerate()
        # CSS only. Every consumer of this bundle asks for stylesheets and
        # disables JS -- t-js="False" in mailing_mobile_preview_content.xml,
        # js: false in mass_mailing_iframe.js and add_snippet_dialog.js -- and
        # it includes html_editor.assets_media_dialog/assets_readonly, both
        # declared ESM, which cannot be concatenated into this non-ESM bundle.
        # Putting it in js_assets makes _pregenerate_assets_bundles raise
        # ModuleSyntaxInLegacyBundleError and take the post_install phase down.
        return (js_assets, css_assets | {"mass_mailing.assets_iframe_style"})
