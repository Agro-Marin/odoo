/** @odoo-module native */
import { Component } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { Dialog } from "@web/ui/dialog";
const log = makeLogger("pos.popup.sync");
export class SyncPopup extends Component {
    static components = { Dialog };
    static template = "point_of_sale.SyncPopup";
    static props = ["close", "confirm", "title"];

    async confirm(fullReload) {
        log.pipeline("confirm", () => ({ title: this.props.title, fullReload }));
        this.props.confirm(fullReload);
        this.props.close();
    }
}
