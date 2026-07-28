// @ts-check
/** @odoo-module native */

/** @module @web/fields/media/contact_image/contact_image_field - Image field variant with fallback to a preview image when empty */

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
     * @param {string} imageFieldName Field name to fetch the image from
     * @returns {string} Image URL, falling back to preview image when primary is empty
     */
    getUrl(imageFieldName) {
        if (
            this.props.previewImage &&
            (!this.props.record.data[this.props.name] || !this.state.isValid)
        ) {
            const previewData = this.props.record.data[imageFieldName];
            if (isBinarySize(previewData)) {
                this.lastURL = imageUrl(
                    this.props.record.resModel,
                    this.props.record.resId,
                    imageFieldName,
                    { unique: this.rawCacheKey },
                );
                return this.lastURL;
            } else if (previewData) {
                const magic = fileTypeMagicWordMap[previewData[0]] || "png";
                this.lastURL = `data:image/${magic};base64,${previewData}`;
                return this.lastURL;
            }
        }
        return super.getUrl(imageFieldName);
    }

    /** @returns {string} CSS classes with reduced opacity when image is missing */
    get imgClass() {
        let classes = super.imgClass;
        if (!this.props.record.data[this.props.name] || !this.state.isValid) {
            classes += " opacity-100 opacity-25-hover";
        }
        return classes;
    }

    /** @returns {boolean} Whether the field contains valid image data */
    get containsValidImage() {
        return this.props.record.data[this.props.name] && this.state.isValid;
    }
}

export const contactImageField = {
    ...imageField,
    component: ContactImageField,
    // Unlike the plain `image` widget — which only feeds `preview_image` to
    // `imageUrl()` as a field NAME for the server to resolve — this variant
    // READS the preview off the record (`getUrl`), so the field has to be in
    // the read spec. Spreads the inherited `write_date` dependency rather than
    // replacing it: the array form above would otherwise be shadowed.
    fieldDependencies: ({ options }) => [
        { name: "write_date", type: "datetime" },
        ...(options.preview_image
            ? [{ name: options.preview_image, optional: true, readonly: true }]
            : []),
    ],
};

registerField("contact_image", contactImageField);
