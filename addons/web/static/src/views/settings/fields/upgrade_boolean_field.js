// @ts-check
/** @odoo-module native */

/** @module @web/views/settings/fields/upgrade_boolean_field - Boolean field for settings that shows an Enterprise upgrade dialog when checked */

import { useService } from "@web/core/utils/hooks";
import { registerField } from "@web/fields/_registry";
import { BooleanField, booleanField } from "@web/fields/basic/boolean/boolean_field";

import { UpgradeDialog } from "./upgrade_dialog.js";

export class UpgradeBooleanField extends BooleanField {
    setup() {
        super.setup();
        this.dialogService = useService("dialog");
        this.isEnterprise = odoo.info && odoo.info.isEnterprise;
    }

    async onChange(newValue) {
        if (!this.isEnterprise) {
            this.dialogService.add(
                UpgradeDialog,
                {},
                {
                    onClose: () => {
                        this.props.record.update({ [this.props.name]: false });
                    },
                },
            );
        } else {
            super.onChange(/** @type {any} */ (newValue));
        }
    }
}

export const upgradeBooleanField = {
    ...booleanField,
    component: UpgradeBooleanField,
    additionalClasses: [...(booleanField.additionalClasses || []), "o_field_boolean"],
};

registerField("upgrade_boolean", upgradeBooleanField);
