import base64
import json

from odoo import Command, api, fields, models


class Web_TourTour(models.Model):
    """Interactive tour definitions for user onboarding and automated testing."""

    _name = "web_tour.tour"
    _description = "Tours"
    _order = "sequence, name, id"

    name = fields.Char(required=True)
    step_ids = fields.One2many("web_tour.tour.step", "tour_id")
    url = fields.Char(string="Starting URL", default="/odoo")
    sharing_url = fields.Char(compute="_compute_sharing_url", string="Sharing URL")
    rainbow_man_message = fields.Html(
        default="<b>Good job!</b> You went through all steps of this tour.",
        translate=True,
    )
    sequence = fields.Integer(default=1000)
    custom = fields.Boolean(string="Custom")
    user_consumed_ids = fields.Many2many("res.users")

    _uniq_name = models.Constraint(
        "unique(name)",
        "A tour already exists with this name . Tour's name must be unique!",
    )

    @api.depends("name")
    def _compute_sharing_url(self):
        """Build a shareable URL that auto-starts this tour."""
        for tour in self:
            tour.sharing_url = f"{tour.get_base_url()}/odoo?tour={tour.name}"

    @api.model
    def consume(self, tour_name):
        """Mark *tour_name* as consumed by the current user and return the next tour."""
        if self.env.user._is_internal():
            tour = self.search([("name", "=", tour_name)], limit=1)
            if tour:
                tour.sudo().user_consumed_ids = [Command.link(self.env.user.id)]
        return self.get_current_tour()

    @api.model
    def get_current_tour(self):
        """Return the JSON of the next unconsumed system tour, or ``False``."""
        user = self.env.user
        if not (user.tour_enabled and user._is_internal()):
            return False
        tour = self.search(
            [("custom", "=", False), ("user_consumed_ids", "not in", user.id)],
            limit=1,
        )
        return tour._get_tour_json() if tour else False

    @api.model
    def get_tour_json_by_name(self, tour_name):
        """Return the JSON representation of the tour identified by *tour_name*."""
        tour = self.search([("name", "=", tour_name)], limit=1)
        return tour._get_tour_json()

    def _get_tour_json(self):
        """Serialize the tour and its steps into a JSON-compatible dict."""
        self.ensure_one()
        return {
            "name": self.name,
            "url": self.url,
            "custom": self.custom,
            "steps": self.step_ids.get_steps_json(),
            "rainbowManMessage": self.rainbow_man_message,
        }

    def export_js_file(self):
        """Export the tour as a downloadable JavaScript module file."""
        self.ensure_one()
        js_content = f"""import {{ registry }} from '@web/core/registry';

registry.category("web_tour.tours").add("{self.name}", {{
    url: "{self.url}",
    steps: () => {json.dumps(self.step_ids.get_steps_json(), indent=4)}
}})"""

        attachment = self.env["ir.attachment"].create(
            {
                "datas": base64.b64encode(js_content.encode()),
                "name": f"{self.name}.js",
                "mimetype": "application/javascript",
                "res_model": "web_tour.tour",
                "res_id": self.id,
            }
        )

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
        }


class Web_TourTourStep(models.Model):
    """Individual step within a tour, defining a trigger element and action."""

    _name = "web_tour.tour.step"
    _description = "Tour's step"
    _order = "sequence, id"

    trigger = fields.Char(required=True)
    content = fields.Char()
    tooltip_position = fields.Selection(
        selection=[
            ["bottom", "Bottom"],
            ["top", "Top"],
            ["right", "Right"],
            ["left", "Left"],
        ],
        default="bottom",
    )
    tour_id = fields.Many2one(
        "web_tour.tour", required=True, index=True, ondelete="cascade"
    )
    run = fields.Char()
    sequence = fields.Integer()

    def get_steps_json(self):
        """Serialize steps into a list of camelCase dicts for the JS client."""
        return [
            {
                "trigger": step["trigger"],
                "tooltipPosition": step["tooltip_position"],
                "run": step["run"],
                **({"content": step["content"]} if step["content"] else {}),
            }
            for step in self.read(
                fields=["trigger", "content", "run", "tooltip_position"]
            )
        ]
