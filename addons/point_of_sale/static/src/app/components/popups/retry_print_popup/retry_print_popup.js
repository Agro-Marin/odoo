/** @odoo-module native */
import { Component } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { _t } from "@web/core/translation";
import { Dialog } from "@web/ui/dialog";
const log = makeLogger("pos.popup.retry_print");
export class RetryPrintPopup extends Component {
    static template = "point_of_sale.RetryPrintPopup";
    static components = { Dialog };
    static props = {
        title: { type: String, optional: true },
        message: { type: String, optional: true },
        canRetry: { type: Boolean, optional: true },
        download: { type: Function, optional: true },
        retry: Function,
        close: Function,
    };
    static defaultProps = {
        title: _t("Printing failed"),
        message: _t(
            "An unknown error occurred. Do you want to download the receipt instead?",
        ),
    };

    onClickDownload() {
        log.logic("download", () => ({ title: this.props.title }));
        this.props.download();
        this.props.close();
    }

    onClickRetry() {
        log.logic("retry", () => ({
            title: this.props.title,
            canRetry: this.props.canRetry,
        }));
        this.props.retry();
        this.props.close();
    }
}
