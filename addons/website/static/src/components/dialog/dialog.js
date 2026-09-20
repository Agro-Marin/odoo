/** @odoo-module native */
import { Component, useState } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { _t } from "@web/core/translation";
import { useChildRef } from "@web/core/utils/hooks";
import { Dialog } from "@web/ui/dialog";

const NO_OP = () => {};

const log = makeLogger("website.dialog.website_dialog");

export class WebsiteDialog extends Component {
    static template = "website.WebsiteDialog";
    static components = { Dialog };
    static props = {
        ...Dialog.props,
        primaryTitle: { type: String, optional: true },
        primaryClick: { type: Function, optional: true },
        secondaryTitle: { type: String, optional: true },
        secondaryClick: { type: Function, optional: true },
        showSecondaryButton: { type: Boolean, optional: true },
        close: { type: Function, optional: true },
        closeOnClick: { type: Boolean, optional: true },
        body: { type: String, optional: true },
        slots: { type: Object, optional: true },
        showFooter: { type: Boolean, optional: true },
    };
    static defaultProps = {
        ...Dialog.defaultProps,
        title: _t("Confirmation"),
        showFooter: true,
        primaryTitle: _t("Ok"),
        secondaryTitle: _t("Cancel"),
        showSecondaryButton: true,
        size: "md",
        closeOnClick: true,
        close: NO_OP,
    };

    setup() {
        useLifecycleLog(log);
        this.state = useState({
            disabled: false,
        });
        this.modalRef = useChildRef();
    }
    /**
     * @param {function|void} handler
     * @returns {function(): Promise}
     */
    protectedClick(handler) {
        return async () => {
            if (this.state.disabled) {
                log.logic("protectedClick ignored: already running");
                return;
            }
            this.state.disabled = true;
            const endClick = log.perf("protectedClick handler", () => ({
                hasHandler: Boolean(handler),
            }));
            if (handler) {
                await handler();
            }
            endClick();
            if (this.props.closeOnClick) {
                log.lifecycle("protectedClick close dialog");
                return this.props.close();
            }
            this.state.disabled = false;
        };
    }

    get contentClasses() {
        const websiteDialogClass = "o_website_dialog";
        if (this.props.contentClass) {
            return `${websiteDialogClass} ${this.props.contentClass}`;
        }
        return websiteDialogClass;
    }
}
