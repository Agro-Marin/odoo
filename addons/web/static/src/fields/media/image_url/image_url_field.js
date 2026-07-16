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
        // URL that already failed to load: used to avoid reverting the fallback
        // back to the broken URL on an unrelated record change (see below).
        this.failedSrc = undefined;
        this.state = useState({
            src: this.props.record.data[this.props.name],
        });

        useRecordObserver((record) => {
            const incoming = record.data[this.props.name];
            // Editing an unrelated field re-fires this observer; without this
            // guard it would overwrite the fallback with the known-bad URL,
            // re-issuing the failing request (flicker + repeated 404s). Only
            // skip when the incoming value is exactly the URL that failed.
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
        this.failedSrc = this.props.record.data[this.props.name];
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
