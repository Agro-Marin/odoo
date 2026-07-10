// @ts-check
/** @odoo-module native */

/** @module @web/views/settings/settings_confirmation_dialog - Three-way dialog (Save/Discard/Stay) for unsaved settings changes */

import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/ui/dialog/confirmation_dialog";

export class SettingsConfirmationDialog
    extends /** @type {any} */ (ConfirmationDialog)
{
    static template = "web.SettingsConfirmationDialog";
    static defaultProps = {
        title: _t("Unsaved changes"),
    };
    static props = {
        .../** @type {any} */ (ConfirmationDialog).props,
        stayHere: { type: Function, optional: true },
    };

    _stayHere() {
        if (this.props.stayHere) {
            this.props.stayHere();
        }
        this.props.close();
    }
}
