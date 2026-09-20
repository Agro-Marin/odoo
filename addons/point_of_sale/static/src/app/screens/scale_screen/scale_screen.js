/** @odoo-module native */
import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { AlertDialog, Dialog } from "@web/ui/dialog";
const log = makeLogger("pos.screen.scale");
export class ScaleScreen extends Component {
    static template = "point_of_sale.ScaleScreen";
    static components = { Dialog };
    static props = {
        getPayload: Function,
        close: Function,
    };

    setup() {
        useLifecycleLog(log);
        this.scale = useState(useService("pos_scale"));
        this.dialog = useService("dialog");
        onMounted(() => this.scale.start(this.onError.bind(this)));
        onWillUnmount(() => this.scale.reset());
    }

    confirm() {
        const weight = this.scale.confirmWeight();
        log.pipeline("confirm", () => ({ weight, product: this.scale.product?.name }));
        this.props.getPayload(weight);
        this.props.close();
    }

    onError(message) {
        log.logic("onError", () => ({ message }));
        this.props.getPayload(null);
        this.dialog.add(
            AlertDialog,
            {
                title: _t("Scale error"),
                body: message,
            },
            { onClose: this.props.close },
        );
    }
}
