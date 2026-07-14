from markupsafe import Markup

from odoo import fields, models

# Characters that would let a token value escape its declaration and corrupt the
# shared company stylesheet. Stripped before the value is emitted as raw CSS.
_CSS_UNSAFE = str.maketrans("", "", "{};\n\r")


class ReportTheme(models.Model):
    """A named bundle of report design tokens (skin), orthogonal to
    ``report.layout`` (structure) and to the company brand colors.

    The token values are emitted verbatim as CSS custom properties
    (``--rp-*``) by the ``web.styles_company_report`` template, scoped to the
    per-company ``.o_company_<id>_layout`` selector. Report SCSS consumes those
    tokens, so a theme change re-skins every printed document at once without
    touching a single report template. Fields hold raw CSS values so WeasyPrint
    resolves them directly during PDF rendering.
    """

    _name = "report.theme"
    _description = "Report Theme"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=50)

    # Typography. Empty falls back (in the emit) to the company ``font``, so a
    # theme need only override the roles it cares about. ``font_display`` styles
    # headings, the document number and totals; ``font_body`` styles running
    # text. Values are CSS font-family stacks, e.g. ``Georgia, serif``.
    font_body = fields.Char(
        string="Body font",
        help="CSS font-family for running text. Empty uses the company font.",
    )
    font_display = fields.Char(
        string="Display font",
        help="CSS font-family for headings, document number and totals. "
        "Empty uses the body font.",
    )

    # Rhythm & shape. Raw CSS lengths dropped straight into the token block.
    row_padding = fields.Char(
        string="Table row padding",
        default="0.5rem",
        help="Vertical padding of table rows (CSS length), e.g. 0.3rem for a "
        "dense ledger or 0.7rem for a roomier document.",
    )
    border_radius = fields.Char(
        string="Corner radius",
        default="0",
        help="Corner radius for totals bands and boxed elements (CSS length).",
    )
    rule_weight = fields.Char(
        string="Rule weight",
        default="1px",
        help="Thickness of the accent rule under table headers (CSS length).",
    )

    def _report_css_vars(self, primary: str, secondary: str, base_font: str) -> Markup:
        """Return the ``--rp-*`` custom-property block as raw (unescaped) CSS.

        Called from ``web.styles_company_report`` per company. Emitting raw is
        required because font stacks contain quotes/commas that ``t-out`` would
        HTML-escape into ``&#39;`` — invalid inside a stylesheet. Values are
        stripped of characters that could break out of the declaration; colors
        come from the company brand, the rest from this theme (defaults when no
        theme is set, i.e. ``self`` is an empty recordset).
        """
        theme = self[:1]

        def css(value: str) -> str:
            return str(value).translate(_CSS_UNSAFE).strip()

        body = css(theme.font_body or base_font)
        display = css(theme.font_display or body)
        return Markup(
            "--rp-accent: %s;\n"
            "--rp-secondary: %s;\n"
            "--rp-font: %s;\n"
            "--rp-font-display: %s;\n"
            "--rp-density: %s;\n"
            "--rp-radius: %s;\n"
            "--rp-rule: %s;"
        ) % (
            # Markup.__mod__ escapes each operand; wrap the already-sanitized
            # font/length values in Markup so they pass through verbatim.
            css(primary),
            css(secondary),
            Markup(body),
            Markup(display),
            Markup(css(theme.row_padding or "0.5rem")),
            Markup(css(theme.border_radius or "0")),
            Markup(css(theme.rule_weight or "1px")),
        )
