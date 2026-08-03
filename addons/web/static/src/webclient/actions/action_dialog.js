// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_dialog */

import { useOwnDebugContext } from "@web/core/debug/debug_context";
import { Dialog } from "@web/ui/dialog/dialog";
import { DebugMenu } from "@web/webclient/debug/debug_menu";

export class ActionDialog extends Dialog {
    static components = {
        .../** @type {any} */ (Dialog).components,
        DebugMenu,
    };
    static template = "web.ActionDialog";
    static props = {
        .../** @type {any} */ (Dialog).props,
        close: Function,
        slots: { optional: true },
        ActionComponent: { optional: true },
        actionProps: { optional: true },
        actionType: { optional: true },
        title: { optional: true },
    };
    static defaultProps = {
        ...Dialog.defaultProps,
        withBodyPadding: false,
    };

    setup() {
        super.setup();
        useOwnDebugContext();
    }
}
