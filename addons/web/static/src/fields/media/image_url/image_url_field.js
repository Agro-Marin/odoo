// @ts-check
/** @odoo-module native */

import { useState } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { registerField } from "@web/fields/_registry";
import { FieldComponent } from "@web/fields/field_component";
import { fieldHandleFor } from "@web/fields/field_handle";
import { imageDimensionAttributes, imageSizeOption } from "@web/fields/field_options";
import { parseDimensionAttr } from "@web/fields/field_utils";
import { useRecordObserver } from "@web/fields/hooks/record_observer";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class ImageUrlField extends FieldComponent {
    static template = "web.ImageUrlField";
    static props = {
        ...standardFieldProps,
        width: { type: Number, optional: true },
        height: { type: Number, optional: true },
    };

    static fallbackSrc = "/web/static/img/placeholder.png";

    /** @type {{ src: any }} */
    state;

    setup() {
        this.notification = useService("notification");
        this.failedSrc = undefined;
        this.state = useState({
            src: this.field.value,
        });

        useRecordObserver((record) => {
            const incoming = fieldHandleFor(record, this.props.name).value;
            if (incoming === this.failedSrc) {
                return;
            }
            this.state.src = incoming;
        });
    }

    get sizeStyle() {
        const width = this.props.width;
        const height = this.props.height;
        let style = width ? `max-width: ${width}px;` : `width: auto;`;
        style += height ? `max-height: ${height}px` : `height: auto`;
        return style;
    }

    onLoadFailed() {
        this.failedSrc = this.field.value;
        this.state.src = /** @type {any} */ (this.constructor).fallbackSrc;
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
const imageUrlField = {
    component: ImageUrlField,
    displayName: _t("Image"),
    supportedOptions: [imageSizeOption()],
    supportedAttributes: [...imageDimensionAttributes()],
    supportedTypes: ["char"],
    extractProps: ({ attrs, options }) => ({
        width: options.size ? options.size[0] : parseDimensionAttr(attrs.width),
        height: options.size ? options.size[1] : parseDimensionAttr(attrs.height),
    }),
};

registerField("image_url", imageUrlField);
