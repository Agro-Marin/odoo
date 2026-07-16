/** @odoo-module native */
import { onMounted, onWillUnmount } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";
export class AvatarUserFormViewDialog extends FormViewDialog {
    setup() {
        super.setup();
        Object.assign(this.viewProps, {
            buttonTemplate: this.props.isToMany
                ? "mail.UserFormViewDialog.ToMany.buttons"
                : "mail.UserFormViewDialog.ToOne.buttons",
        });

        onMounted(() => {
            this._focusTimeout = browser.setTimeout(() => {
                // optional chain: a dialog destroyed in the same tick has no
                // modal element anymore
                const input = this.modalRef.el?.querySelector("#name_0");
                input?.focus();
            });
        });
        onWillUnmount(() => browser.clearTimeout(this._focusTimeout));
    }
}
