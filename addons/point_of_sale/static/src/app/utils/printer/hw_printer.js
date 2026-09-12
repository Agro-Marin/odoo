/** @odoo-module native */
import { BasePrinter } from "@point_of_sale/app/utils/printer/base_printer";
import { makeLogger } from "@web/core/debug/debug_logger";
import { rpc } from "@web/core/network";
const log = makeLogger("pos.printer.hw");
export class HWPrinter extends BasePrinter {
    /**
     * @param {Object} params
     * @param {string} params.url
     */
    setup(params) {
        super.setup(...arguments);
        this.url = params.url;
    }

    sendAction(data) {
        log.pipeline("sendAction", () => ({
            url: this.url,
            action: data.action,
            bytes: data.receipt?.length,
        }));
        return rpc(`${this.url}/hw_proxy/default_printer_action`, { data });
    }

    /**
     * @override
     */
    openCashbox() {
        return this.sendAction({ action: "cashbox" });
    }

    /**
     * @override
     */
    sendPrintingJob(img) {
        return this.sendAction({ action: "print_receipt", receipt: img });
    }
}
