"""Tests for report.theme — the report design-token (skin) system.

Themes emit ``--rp-*`` CSS custom properties into the per-company report
stylesheet (``web.styles_company_report``); the report SCSS consumes them.
"""

import base64

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "web_unit", "report_theme")
class TestReportTheme(TransactionCase):
    def test_css_vars_defaults_on_empty_recordset(self):
        """No theme set: tokens still emit, with the built-in defaults."""
        css = self.env["report.theme"]._report_css_vars("#111", "#222", "Lato")
        self.assertIn("--rp-accent: #111;", css)
        self.assertIn("--rp-secondary: #222;", css)
        self.assertIn("--rp-font: Lato;", css)
        self.assertIn("--rp-density: 0.5rem;", css)
        self.assertIn("--rp-rule: 1px;", css)

    def test_font_fallback_chain(self):
        """font_display falls back to font_body, font_body to the company font."""
        theme = self.env["report.theme"].create({"name": "T", "font_body": False})
        css = theme._report_css_vars("#111", "#222", "Georgia, serif")
        self.assertIn("--rp-font: Georgia, serif;", css)
        self.assertIn("--rp-font-display: Georgia, serif;", css)

        theme.font_display = "'Playfair Display', serif"
        css = theme._report_css_vars("#111", "#222", "Lato")
        self.assertIn("--rp-font: Lato;", css)
        self.assertIn("--rp-font-display: 'Playfair Display', serif;", css)

    def test_css_vars_strip_declaration_breakers(self):
        """Braces/semicolons/newlines cannot escape the token declaration."""
        theme = self.env["report.theme"].create(
            {
                "name": "Hostile",
                "font_body": "Georgia; } body { color: red } \n",
                "row_padding": "1rem;}{",
            }
        )
        css = str(theme._report_css_vars("#111", "#222", "Lato"))
        self.assertNotIn("{", css.replace("&#39;", ""))
        self.assertNotIn("}", css)
        # Semicolons survive only as the per-token separators the template
        # emits itself: one per token line.
        self.assertEqual(css.count(";"), 7)

    def test_company_stylesheet_carries_tokens(self):
        """The rendered company report stylesheet embeds the theme tokens."""
        css = base64.b64decode(self.env["res.company"]._get_asset_style_b64()).decode()
        for token in ("--rp-accent", "--rp-font", "--rp-density", "--rp-rule"):
            self.assertIn(token, css)

    def test_default_theme_backfill_is_idempotent(self):
        modern = self.env.ref("web.report_theme_modern")
        ledger = self.env.ref("web.report_theme_ledger")
        company = self.env["res.company"].create(
            {"name": "Backfill Co", "report_theme_id": False}
        )
        chosen = self.env["res.company"].create(
            {"name": "Chosen Co", "report_theme_id": ledger.id}
        )
        self.env["res.company"]._set_default_report_theme()
        self.assertEqual(company.report_theme_id, modern)
        # Never clobbers an explicit choice.
        self.assertEqual(chosen.report_theme_id, ledger)

    def test_theme_change_regenerates_company_stylesheet(self):
        """Switching the company theme refreshes the report style attachment."""
        attachment = self.env.ref("web.asset_styles_company_report")
        before = attachment.datas
        self.env.company.report_theme_id = self.env.ref("web.report_theme_editorial")
        after = self.env.ref("web.asset_styles_company_report").datas
        self.assertNotEqual(before, after)
        self.assertIn("Georgia", base64.b64decode(after).decode())

    def test_editing_theme_token_regenerates_company_stylesheet(self):
        """Editing a theme's own tokens reflows the shared company stylesheet.

        The asset is otherwise only rebuilt on res.company writes, so without
        the report.theme write hook a theme edit would not reach any report.
        """
        theme = self.env.ref("web.report_theme_modern")
        self.env.company.report_theme_id = theme
        before = self.env.ref("web.asset_styles_company_report").datas
        theme.row_padding = "2.5rem"
        after = self.env.ref("web.asset_styles_company_report").datas
        self.assertNotEqual(before, after)
        self.assertIn("2.5rem", base64.b64decode(after).decode())

    def test_editing_theme_non_token_field_skips_regeneration(self):
        """A non-token write (e.g. sequence) leaves the shared asset untouched."""
        theme = self.env.ref("web.report_theme_modern")
        self.env.company.report_theme_id = theme
        before = self.env.ref("web.asset_styles_company_report").datas
        theme.sequence += 5
        after = self.env.ref("web.asset_styles_company_report").datas
        self.assertEqual(before, after)

    def test_condensed_theme_shipped(self):
        """The Condensed theme ships and emits its condensed display face."""
        theme = self.env.ref("web.report_theme_condensed")
        css = str(theme._report_css_vars("#111", "#222", "Lato"))
        self.assertIn("--rp-font-display: Oswald", css)
