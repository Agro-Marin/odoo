/** @odoo-module native */
import { Component } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useService } from "@web/core/utils/hooks";
import { renderToElement } from "@web/core/utils/render";
import { AlertDialog } from "@web/ui/dialog";
const log = makeLogger("pos.report.sale_details");
export async function handleSaleDetails(pos, hardwareProxy, dialog) {
    const endDetails = log.perf("[report] get_sale_details");
    const saleDetails = await pos.data.call(
        "report.point_of_sale.report_saledetails",
        "get_sale_details",
        [false, false, false, [pos.session.id]],
    );
    endDetails({
        session: pos.session.id,
        products: saleDetails?.products?.length,
        payments: saleDetails?.payments?.length,
    });
    const report = renderToElement(
        "point_of_sale.SaleDetailsReport",
        Object.assign({}, saleDetails, {
            date: new Date().toLocaleString(),
            pos: pos,
            formatCurrency: pos.env.utils.formatCurrency,
        }),
    );
    const { successful, message } = await hardwareProxy.printer.printReceipt(report);
    log.pipeline("[report] sale details printed", () => ({
        session: pos.session.id,
        successful,
        error: successful ? undefined : message?.title,
    }));
    if (!successful) {
        dialog.add(AlertDialog, {
            title: message.title,
            body: message.body,
        });
    }
}
export class SaleDetailsButton extends Component {
    static template = "point_of_sale.SaleDetailsButton";
    static props = {
        isHeaderButton: { type: Boolean, optional: true },
    };
    setup() {
        super.setup(...arguments);
        this.pos = usePos();
        this.dialog = useService("dialog");
        this.hardwareProxy = useService("hardware_proxy");
    }

    async onClick() {
        await handleSaleDetails(this.pos, this.hardwareProxy, this.dialog);
    }
}
