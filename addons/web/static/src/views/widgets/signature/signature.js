// @ts-check
/** @odoo-module native */

/** @module @web/views/widgets/signature/signature */

import { Component } from "@odoo/owl";
import { SignatureDialog } from "@web/components/signature/signature_dialog";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

export class SignatureWidget extends Component {
    static template = "web.SignatureWidget";
    static props = {
        ...standardWidgetProps,
        fullName: { type: String, optional: true },
        highlight: { type: Boolean, optional: true },
        string: { type: String },
        signatureField: { type: String, optional: true },
    };

    /** @type {import("services").ServiceFactories["dialog"]} */
    dialogService;
    /** @type {import("services").ServiceFactories["orm"]} */
    orm;

    setup() {
        this.dialogService = useService("dialog");
        this.orm = useService("orm");
    }

    onClickSignature() {
        const nameAndSignatureProps = {
            mode: "draw",
            displaySignatureRatio: 3,
            signatureType: "signature",
            noInputName: true,
        };
        const { fullName, record } = this.props;
        let defaultName = "";
        if (fullName) {
            let signName;
            const fullNameData = record.data[fullName];
            if (record.fields[fullName].type === "many2one") {
                signName = fullNameData?.display_name;
            } else {
                signName = fullNameData;
            }
            defaultName = signName || undefined;
        }

        const dialogProps = {
            defaultName,
            nameAndSignatureProps,
            uploadSignature: (/** @type {{ signatureImage: string }} */ data) =>
                this.uploadSignature(data),
        };
        this.dialogService.add(SignatureDialog, dialogProps);
    }

    /**
     * @param {{ signatureImage: string }} param0
     */
    async uploadSignature({ signatureImage }) {
        const file = signatureImage.split(",")[1];
        const record = this.props.record;
        const { model, resModel, resId } = record;
        const signatureField = this.props.signatureField;
        if (!resId) {
            await record.update({ [signatureField]: file });
            await record.save();
            return;
        }
        // eslint-disable-next-line no-restricted-syntax -- deliberate raw access; see comment above
        const orm = this.env.services.orm;

        await orm.write(resModel, [resId], { [signatureField]: file });
        await record.load();
        model.notify();
    }
}

/** @type {import("registries").ViewWidgetsRegistryItemShape} */
export const signatureWidget = {
    component: SignatureWidget,
    extractProps: ({ attrs }) => {
        const { full_name: fullName, highlight, signature_field, string } = attrs;
        return {
            fullName,
            highlight: !!highlight,
            string,
            signatureField: signature_field || "signature",
        };
    },
};

registry.category("view_widgets").add("signature", signatureWidget);
