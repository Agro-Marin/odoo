/** @odoo-module native */
import { ConfirmationDialog } from "@web/ui/dialog";
import { _t } from "@web/core/translation";

export class AccessRightsUpdateConfirmationDialog extends ConfirmationDialog {
    static template = "documents.AccessRightsUpdateConfirmationDialog";

    static props = {
        ...ConfirmationDialog.props,
        destinationFolder: { type: Object },
    };

    get title() {
        return _t("Moving to: %s", this.props.destinationFolder.display_name);
    }
}
