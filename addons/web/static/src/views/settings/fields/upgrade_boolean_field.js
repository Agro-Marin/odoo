// @ts-check
/** @odoo-module native */

import { useService } from "@web/core/utils/hooks";
import { registerField } from "@web/fields/_registry";
import { BooleanField, booleanField } from "@web/fields/basic/boolean/boolean_field";

import { UpgradeDialog } from "./upgrade_dialog.js";

export class UpgradeBooleanField extends BooleanField {
    /** @type {import("services").ServiceFactories["dialog"]} */
    dialogService;

    setup() {
        super.setup();
        this.dialogService = useService("dialog");
        this.isEnterprise = odoo.info && odoo.info.isEnterprise;
    }

    /** @param {any} newValue */
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

/** @type {import("registries").FieldsRegistryItemShape} */
export const upgradeBooleanField = {
    ...booleanField,
    component: UpgradeBooleanField,
    additionalClasses: [
        .../** @type {string[]} */ (
            /** @type {Record<string, any>} */ (booleanField).additionalClasses || []
        ),
        "o_field_boolean",
    ],
};

registerField("upgrade_boolean", upgradeBooleanField);
