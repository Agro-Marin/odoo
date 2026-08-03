/** @odoo-module native */
import { _t } from "@web/core/translation";
import { ConfirmationDialog } from "@web/ui/dialog";
export class QRPopup extends ConfirmationDialog {
    static template = "point_of_sale.QRConfirmationDialog";
    static props = {
        ...ConfirmationDialog.props,
        line: Object,
        order: Object,
        qrCode: String,
    };
    static defaultProps = {
        ...ConfirmationDialog.defaultProps,
        confirmLabel: _t("Confirm Payment"),
        cancelLabel: _t("Cancel Payment"),
        title: _t("QR Code Payment"),
    };

    setup() {
        super.setup();
        this.props.body = _t("Please scan the QR code with %s", this.props.title);
        this.amount = this.env.utils.formatCurrency(this.props.line.amount);
    }
}
