from odoo import _, models


class MixinPaymentQrCode(models.AbstractModel):
    _name = "mixin.payment.qr.code"
    _description = "Payment QR Code Rendering"

    def _can_render_payment_qr_code(self):
        self.ensure_one()
        return bool(
            self.partner_bank_id
            and self.partner_bank_id.allow_out_payment
            and self.payment_channel_id.code == "manual"
            and self.payment_type == "outbound"
            and self.currency_id
            and self.amount
        )

    def _render_payment_qr_code(self, amount, communication):
        self.ensure_one()
        if not self._can_render_payment_qr_code():
            return False
        qr_code = self.partner_bank_id.build_qr_code_base64(
            amount, communication, communication, self.currency_id, self.partner_id
        )
        if not qr_code:
            return False
        return f'''
            <img class="border border-dark rounded" src="{qr_code}"/>
            <br/>
            <strong class="text-center">{_("Scan me with your banking app.")}</strong>
        '''
