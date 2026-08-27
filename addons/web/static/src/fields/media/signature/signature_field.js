// @ts-check
/** @odoo-module native */

import { onWillRender, useState } from "@odoo/owl";
import { SignatureDialog } from "@web/components/signature/signature_dialog";
import { getSignatureDefaultName } from "@web/components/signature/signature_name";
import { _t } from "@web/core/translation";
import { isBinarySize } from "@web/core/utils/format/binary";
import { useService } from "@web/core/utils/hooks";
import { imageUrl } from "@web/core/utils/urls";
import { registerField } from "@web/fields/_registry";
import { FieldComponent } from "@web/fields/field_component";
import { fieldHandleFor } from "@web/fields/field_handle";
import { imageDimensionAttributes, imageSizeOption } from "@web/fields/field_options";
import { parseDimensionAttr } from "@web/fields/field_utils";
import { fileTypeMagicWordMap } from "@web/fields/media/image/image_field";
import { standardFieldProps } from "@web/fields/standard_field_props";

const placeholder = "/web/static/img/placeholder.png";

export class SignatureField extends FieldComponent {
    static template = "web.SignatureField";
    static props = {
        ...standardFieldProps,
        defaultFont: { type: String },
        fullName: { type: String, optional: true },
        height: { type: Number, optional: true },
        previewImage: { type: String, optional: true },
        width: { type: Number, optional: true },
        type: {
            validate: (t) => ["initial", "signature"].includes(t),
            optional: true,
        },
    };
    static defaultProps = {
        type: "signature",
    };

    /** @type {import("services").ServiceFactories["dialog"]} */
    dialogService;
    /** @type {number} */
    displaySignatureRatio;
    /** @type {import("services").ServiceFactories["notification"]} */
    notification;
    /** @type {{ isValid: boolean }} */
    state;

    setup() {
        this.displaySignatureRatio = 3;

        this.dialogService = useService("dialog");
        this.notification = useService("notification");
        this.state = useState({
            isValid: true,
        });
        let resId = this.props.record.resId;
        let value = this.value;
        onWillRender(() => {
            const { record } = this.props;
            const nextValue = fieldHandleFor(record, this.props.name).value;
            if (record.resId !== resId || value !== nextValue) {
                this.state.isValid = true;
            }
            resId = record.resId;
            value = nextValue;
        });
    }

    /** @returns {string} */
    get rawCacheKey() {
        return this.props.record.data.write_date;
    }

    /** @returns {string} */
    get getUrl() {
        const { name, previewImage, record } = this.props;
        if (this.state.isValid && this.value) {
            if (isBinarySize(this.value)) {
                return imageUrl(record.resModel, record.resId, previewImage || name, {
                    unique: this.rawCacheKey,
                });
            } else {
                const magic = fileTypeMagicWordMap[this.value[0]] || "png";
                return `data:image/${magic};base64,${this.field.value}`;
            }
        }
        return placeholder;
    }

    /** @returns {string} */
    get sizeStyle() {
        let { width, height } = this.props;

        if (!this.value) {
            if (width && height) {
                width = Math.min(width, this.displaySignatureRatio * height);
                height = width / this.displaySignatureRatio;
            } else if (width) {
                height = width / this.displaySignatureRatio;
            } else if (height) {
                width = height * this.displaySignatureRatio;
            }
        }

        let style = "";
        if (width) {
            style += `width:${width}px; max-width:${width}px;`;
        }
        if (height) {
            style += `height:${height}px; max-height:${height}px;`;
        }
        return style;
    }

    /** @returns {string|false} */
    get value() {
        return this.field.value;
    }

    onClickSignature() {
        if (!this.props.readonly) {
            const nameAndSignatureProps = {
                displaySignatureRatio: 3,
                signatureType: this.props.type,
                noInputName: true,
            };
            const defaultName = getSignatureDefaultName(
                this.props.record,
                this.props.fullName,
            );

            nameAndSignatureProps.defaultFont = this.props.defaultFont;

            const dialogProps = {
                defaultName,
                nameAndSignatureProps,
                uploadSignature: (signature) => this.uploadSignature(signature),
            };
            this.dialogService.add(SignatureDialog, dialogProps);
        }
    }

    onLoadFailed() {
        this.state.isValid = false;
        this.notification.add(_t("Could not display the selected image"), {
            type: "danger",
        });
    }

    /** @private */
    uploadSignature({ signatureImage }) {
        return this.field.update(signatureImage.split(",")[1] || false);
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const signatureField = {
    component: SignatureField,
    displayName: _t("Signature"),
    fieldDependencies: ({ options }) => [
        { name: "write_date", type: "datetime" },
        ...(options.full_name
            ? [{ name: options.full_name, optional: true, readonly: true }]
            : []),
    ],
    supportedAttributes: [...imageDimensionAttributes()],
    supportedTypes: ["binary"],
    supportedOptions: [
        {
            label: _t("Prefill with"),
            name: "full_name",
            type: "field",
            availableTypes: ["char", "many2one"],
            help: _t("The selected field will be used to pre-fill the signature"),
        },
        {
            label: _t("Default font"),
            name: "default_font",
            type: "string",
        },
        imageSizeOption(),
        {
            label: _t("Preview image field"),
            name: "preview_image",
            type: "field",
            availableTypes: ["binary"],
        },
        {
            label: _t("Kind"),
            name: "type",
            type: "selection",
            choices: [
                { label: _t("Signature"), value: "signature" },
                { label: _t("Initials"), value: "initial" },
            ],
            default: "signature",
        },
    ],
    extractProps: ({ attrs, options }) => ({
        defaultFont: options.default_font || "",
        fullName: options.full_name,
        height: options.size
            ? options.size[1] || undefined
            : parseDimensionAttr(attrs.height),
        previewImage: options.preview_image,
        type: options.type,
        width: options.size
            ? options.size[0] || undefined
            : parseDimensionAttr(attrs.width),
    }),
};

registerField("signature", signatureField);
