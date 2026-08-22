// @ts-check
/** @odoo-module native */

import { isBinarySize } from "@web/core/utils/format/binary";
import { imageUrl } from "@web/core/utils/urls";
import { registerField } from "@web/fields/_registry";
import {
    fileTypeMagicWordMap,
    ImageField,
    imageField,
} from "@web/fields/media/image/image_field";

export class ContactImageField extends ImageField {
    static template = "web.ContactImageField";

    /**
     * @param {string} imageFieldName
     * @returns {string}
     */
    getUrl(imageFieldName) {
        if (this.props.previewImage && (!this.field.value || !this.state.isValid)) {
            const previewData = this.props.record.data[imageFieldName];
            if (isBinarySize(previewData)) {
                const url = imageUrl(
                    this.props.record.resModel,
                    this.props.record.resId,
                    imageFieldName,
                    { unique: this.rawCacheKey },
                );
                this.lastURL = { field: imageFieldName, url };
                return url;
            } else if (previewData) {
                const magic = fileTypeMagicWordMap[previewData[0]] || "png";
                const url = `data:image/${magic};base64,${previewData}`;
                this.lastURL = { field: imageFieldName, url };
                return url;
            }
        }
        return super.getUrl(imageFieldName);
    }

    /** @returns {string} */
    get imgClass() {
        let classes = super.imgClass;
        if (!this.field.value || !this.state.isValid) {
            classes += " opacity-100 opacity-25-hover";
        }
        return classes;
    }

    /** @returns {boolean} */
    get containsValidImage() {
        return this.field.value && this.state.isValid;
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
const contactImageField = {
    ...imageField,
    component: ContactImageField,
    fieldDependencies: ({ options }) => [
        { name: "write_date", type: "datetime" },
        ...(options.preview_image
            ? [{ name: options.preview_image, optional: true, readonly: true }]
            : []),
    ],
};

registerField("contact_image", contactImageField);
