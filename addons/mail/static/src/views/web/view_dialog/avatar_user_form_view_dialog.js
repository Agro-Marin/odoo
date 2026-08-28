/** @odoo-module native */
import { onMounted, onWillUnmount } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { FormViewDialog } from "@web/views/view_dialogs";
export class AvatarUserFormViewDialog extends FormViewDialog {
    static defaultProps = { ...FormViewDialog.defaultProps, size: "md" };

    setup() {
        super.setup();
        Object.assign(this.viewProps, {
            buttonTemplate: this.props.isToMany
                ? "mail.UserFormViewDialog.ToMany.buttons"
                : "mail.UserFormViewDialog.ToOne.buttons",
        });

        onMounted(() => {
            this._focusTimeout = browser.setTimeout(() => {
                const input = this.modalRef.el?.querySelector("#name_0");
                input?.focus();
            });
        });
        onWillUnmount(() => browser.clearTimeout(this._focusTimeout));
    }
}
