from odoo import api, fields, models

from odoo.addons.base.models.catalog_mixin import name_uniq_index


class AIModel(models.Model):
    _name = "ai.model"
    _inherit = ["catalog.mixin"]
    _description = "AI Model"
    _order = "provider_id, sequence, name"

    provider_id = fields.Many2one(
        comodel_name="ai.provider",
        required=True,
        index=True,
        ondelete="cascade",
        help="Vendor endpoint this model is reached through",
    )
    code = fields.Char(
        required=True,
        index=True,
        help="Identifier sent as the 'model' parameter on the wire",
    )
    kind = fields.Selection(
        selection=[
            ("chat", "Chat"),
            ("vision", "Vision"),
            ("audio", "Audio"),
            ("embedding", "Embedding"),
        ],
        required=True,
        default="chat",
        help="What this model is called for",
    )
    sequence = fields.Integer(
        default=10,
    )

    has_vision = fields.Boolean(
        default=False,
        help="Can read images sent alongside the prompt",
    )
    supports_streaming = fields.Boolean(
        default=True,
        help="Supports streaming responses",
    )
    supports_function_calling = fields.Boolean(
        default=False,
        help="Supports function/tool calling",
    )
    max_context_window = fields.Integer(
        help="Maximum context window size in tokens",
    )
    max_output_tokens = fields.Integer(
        help="Maximum number of output tokens per request",
    )

    cost_per_1m_input = fields.Float(
        digits=(12, 6),
        help="Cost per 1 million input tokens in USD",
    )
    cost_per_1m_output = fields.Float(
        digits=(12, 6),
        help="Cost per 1 million output tokens in USD",
    )
    cost_per_1m_image = fields.Float(
        digits=(12, 6),
        help="Cost per 1 million pixels for image processing",
    )
    cost_per_audio_minute = fields.Float(
        digits=(12, 6),
        help="Cost per minute of audio processing",
    )

    accuracy_rating = fields.Selection(
        selection=[
            ("1", "Low"),
            ("2", "Medium-Low"),
            ("3", "Medium"),
            ("4", "Medium-High"),
            ("5", "High"),
        ],
        default="3",
        help="Subjective accuracy rating (1-5 scale)",
    )
    speed_rating = fields.Selection(
        selection=[
            ("1", "Slow"),
            ("2", "Medium-Slow"),
            ("3", "Medium"),
            ("4", "Medium-Fast"),
            ("5", "Fast"),
        ],
        default="3",
        help="Response speed rating (1-5 scale)",
    )

    fallback_model_ids = fields.Many2many(
        comodel_name="ai.model",
        relation="ai_model_fallback_rel",
        column1="model_id",
        column2="fallback_id",
        help="Ordered models to try when this one fails. A hop may stay on this "
        "provider — a smaller model on a key you already hold — or cross to "
        "another.",
    )

    _code_uniq = models.Constraint(
        "unique(provider_id, code)",
        "A provider cannot serve the same model code twice!",
    )
    _name_src_uniq = name_uniq_index(
        "provider_id",
        message="This provider already has a model with that name.",
    )

    @api.depends("name", "code")
    def _compute_display_name(self) -> None:
        for record in self:
            if record.code:
                record.display_name = f"{record.name} [{record.code}]"
            else:
                record.display_name = record.name or ""
