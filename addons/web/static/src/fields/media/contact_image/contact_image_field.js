// @ts-check
/** @odoo-module native */

/** @module @web/fields/media/contact_image/contact_image_field - Image field variant with fallback to a preview image when empty */

import { isBinarySize } from "@web/core/utils/format/binary";
import { imageUrl } from "@web/core/utils/urls";
import { registerField } from "@web/fields/_registry";
import { ImageField, imageField } from "@web/fields/media/image/image_field";

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
                this.lastURL = `data:image/png;base64,${previewData}`;
                return this.lastURL;
            }
            // Neither the primary field nor the preview field holds data: fall
            // through to the base placeholder instead of emitting a broken
            // "data:image/png;base64,false" src.
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
};

registerField("contact_image", contactImageField);
