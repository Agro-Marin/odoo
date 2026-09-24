/** @odoo-module native */

import { registry } from "@web/core/registry";
import {
    copyClipboardButtonField,
    CopyClipboardButtonField,
} from "@web/fields/basic/copy_clipboard/copy_clipboard_field";

import { CopyButton } from "@web/components/copy_button";
import { useViewModel } from "@web/model/model";

class PaymentWizardCopyButton extends CopyButton {
    setup() {
        super.setup();
        this.model = useViewModel();
    }

    async onClick() {
        await this.model.mutex.getUnlockedDef();
        return super.onClick();
    }
}

class PaymentWizardCopyClipboardButtonField extends CopyClipboardButtonField {
    static components = { CopyButton: PaymentWizardCopyButton };
}

const paymentWizardCopyClipboardButtonField = {
    ...copyClipboardButtonField,
    component: PaymentWizardCopyClipboardButtonField,
};

registry
    .category("fields")
    .add(
        "PaymentWizardCopyClipboardButtonField",
        paymentWizardCopyClipboardButtonField,
    );
