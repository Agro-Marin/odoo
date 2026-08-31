from odoo import _, fields, models


class LoyaltyReward(models.Model):
    _inherit = "loyalty.reward"

    reward_type = fields.Selection(
        selection_add=[("shipping", "Free Shipping")],
        ondelete={"shipping": "set default"},
    )

    def _description_texts(self, products_per_reward):
        # Overriding _description_texts (not _compute_description) means the
        # "shipping" text goes through the base's per-installed-language,
        # en_US-source-first loop like every other reward type -- a flat
        # `self.description = _("Free shipping")` here bypassed that loop and
        # wrote whatever language the caller happened to be in as the en_US
        # source term.
        descriptions = super()._description_texts(products_per_reward)
        for index, reward in enumerate(self):
            if reward.reward_type != "shipping":
                continue
            reward_string = _("Free shipping")
            if reward.discount_max_amount:
                format_string = "%(amount)g %(symbol)s"
                if reward.currency_id.position == "before":
                    format_string = "%(symbol)s %(amount)g"
                formatted_amount = format_string % {
                    "amount": reward.discount_max_amount,
                    "symbol": reward.currency_id.symbol,
                }
                reward_string += _(" (Max %s)", formatted_amount)
            descriptions[index] = reward_string
        return descriptions
