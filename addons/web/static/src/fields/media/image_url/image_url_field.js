// @ts-check
/** @odoo-module native */

/** @module @web/fields/media/image_url/image_url_field - Image display field that loads from a URL stored in a Char column */

import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { registerField } from "@web/fields/_registry";
import { parseDimensionAttr } from "@web/fields/field_utils";
import { useRecordObserver } from "@web/fields/hooks/record_observer";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class ImageUrlField extends Component {
    static template = "web.ImageUrlField";
    static props = {
        ...standardFieldProps,
        width: { type: Number, optional: true },
        height: { type: Number, optional: true },
    };

    static fallbackSrc = "/web/static/img/placeholder.png";

    setup() {
        this.notification = useService("notification");
        this.state = useState({
            src: this.props.record.data[this.props.name],
        });

        useRecordObserver((record) => {
            this.state.src = record.data[this.props.name];
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
        this.state.src = /** @type {any} */ (this.constructor).fallbackSrc;
    }
}

export const imageUrlField = {
    component: ImageUrlField,
    displayName: _t("Image"),
    supportedOptions: [
        {
            label: _t("Size"),
            name: "size",
            type: "selection",
            choices: [
                { label: _t("Small"), value: "[0,90]" },
                { label: _t("Medium"), value: "[0,180]" },
                { label: _t("Large"), value: "[0,270]" },
            ],
        },
    ],
    supportedTypes: ["char"],
    extractProps: ({ attrs, options }) => ({
        width: options.size ? options.size[0] : parseDimensionAttr(attrs.width),
        height: options.size ? options.size[1] : parseDimensionAttr(attrs.height),
    }),
};

registerField("image_url", imageUrlField);
