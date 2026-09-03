// @ts-check
/** @odoo-module native */

import { Component, useExternalListener } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { useChildRef, useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/ui/dialog";

export class PromoteStudioDialog extends Component {
    static template = "web.PromoteStudioDialog";
    static components = { Dialog };
    static props = {
        title: String,
        close: Function,
    };

    /** @type {boolean} */
    disableClick = false;

    /** @type {import("services").ServiceFactories["orm"]} */
    ormService;
    /** @type {import("services").ServiceFactories["ui"]} */
    uiService;
    /** @type {ReturnType<typeof useChildRef>} */
    modalRef;

    setup() {
        this.ormService = useService("orm");
        this.uiService = useService("ui");

        this.modalRef = useChildRef();

        useExternalListener(window, "mousedown", this.onWindowMouseDown);
    }

    async onClickInstallStudio() {
        this.disableClick = true;
        this.uiService.block();
        const [module] = await this.ormService.searchRead(
            "ir.module.module",
            [["name", "=", "web_studio"]],
            ["id"],
        );
        if (!module) {
            // Nothing to install, and the page is blocked: unblocking and
            // raising says so, where reading through the empty result left a
            // TypeError behind a blocked screen.
            this.uiService.unblock();
            this.disableClick = false;
            throw new Error("web_studio is not available in this database");
        }
        await this.ormService.call("ir.module.module", "button_immediate_install", [
            [module.id],
        ]);
        // on rpc call return, the framework unblocks the page
        // make sure to keep the page blocked until the reload ends.
        this.uiService.unblock();
        browser.localStorage.setItem("openStudioOnReload", "main");
        browser.location.reload();
    }

    /**
     * Close the dialog on outside click.
     */
    /** @param {MouseEvent} ev */
    onWindowMouseDown(ev) {
        const dialogContent = this.modalRef.el?.querySelector(".modal-content");
        if (!dialogContent) {
            return;
        }
        if (
            !this.disableClick &&
            !dialogContent.contains(/** @type {Node} */ (ev.target))
        ) {
            this.props.close();
        }
    }
}

export class PromoteStudioAutomationDialog extends PromoteStudioDialog {
    static template = "web.PromoteStudioAutomationDialog";
}
