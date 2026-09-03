/** @odoo-module native */
import { Component } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { Dialog } from "@web/ui/dialog";
export class CallPermissionDeniedDialog extends Component {
    static components = { Dialog };
    static props = {
        close: Function,
        media: {
            type: String,
            /** @param {string} s */
            validate: (s) => ["camera", "microphone"].includes(s),
            optional: true,
        },
    };
    static template = "discuss.CallPermissionDeniedDialog";

    get title() {
        if (this.props.media === "camera") {
            return _t("Discuss cannot access your camera");
        }
        if (this.props.media === "microphone") {
            return _t("Discuss cannot access your microphone");
        }
        return _t("Discuss cannot access your camera and microphone");
    }

    get permissionStep() {
        if (this.props.media === "camera") {
            return _t("Turn on the camera permission");
        }
        if (this.props.media === "microphone") {
            return _t("Turn on the microphone permission");
        }
        return _t("Turn on the camera and microphone permissions");
    }
}
