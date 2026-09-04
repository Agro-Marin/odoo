from __future__ import annotations

from odoo import fields, models


class DiscussChannel(models.Model):
    _inherit = "discuss.channel"

    def _open_call_history(self) -> models.Model:
        self.check_singleton()
        return (
            self.env["discuss.call.history"]
            .sudo()
            .search(
                [("channel_id", "=", self.id), ("end_dt", "=", False)],
                order="start_dt DESC",
                limit=1,
            )
        )

    def _record_call_media(
        self, attachment, start_ms: int, end_ms: int
    ) -> models.Model:
        self.check_singleton()
        history = self._open_call_history()
        if not history:
            history = (
                self.env["discuss.call.history"]
                .sudo()
                .create({"channel_id": self.id, "start_dt": fields.Datetime.now()})
            )
        return history._add_media_segment(attachment, start_ms, end_ms)
