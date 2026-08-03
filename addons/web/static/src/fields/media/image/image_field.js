// @ts-check
/** @odoo-module native */

/** @module @web/fields/media/image/image_field */

import { Component, onWillRender, status, useState } from "@odoo/owl";
import { isMobileOS } from "@web/core/browser/feature_detection";
import { FileUploader } from "@web/core/file_upload/file_handler";
import { DateTime } from "@web/core/l10n/luxon";
import { _t } from "@web/core/translation";
import { isBinarySize } from "@web/core/utils/format/binary";
import { useService } from "@web/core/utils/hooks";
import { imageUrl } from "@web/core/utils/urls";
import { registerField } from "@web/fields/_registry";
import {
    convertUploadToWebp,
    createWebpVariantAttachments,
    ImageDecodeError,
} from "@web/fields/media/image/image_variants";
import { standardFieldProps } from "@web/fields/standard_field_props";

/** @type {Record<string, string>} */
export const fileTypeMagicWordMap = {
    "/": "jpg",
    R: "gif",
    i: "png",
    P: "svg+xml",
    U: "webp",
};
const placeholder = "/web/static/img/placeholder.png";

export class ImageField extends Component {
    static template = "web.ImageField";
    static components = {
        FileUploader,
    };
    static props = {
        ...standardFieldProps,
        alt: { type: String, optional: true },
        enableZoom: { type: Boolean, optional: true },
        imgClass: { type: String, optional: true },
        zoomDelay: { type: Number, optional: true },
        previewImage: { type: String, optional: true },
        acceptedFileExtensions: { type: String, optional: true },
        width: { type: Number, optional: true },
        height: { type: Number, optional: true },
        reload: { type: Boolean, optional: true },
        convertToWebp: { type: Boolean, optional: true },
    };
    static defaultProps = {
        acceptedFileExtensions: "image/*",
        alt: _t("Binary file"),
        imgClass: "",
        reload: true,
    };

    /** @type {import("services").ServiceFactories["notification"]} */
    notification;
    /** @type {import("services").ServiceFactories["orm"]} */
    orm;
    /** @type {{ isValid: boolean }} */
    state;
    /** @type {{ field: string, url: string } | undefined} */
    lastURL;

    setup() {
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.isMobile = isMobileOS();
        this.state = useState({
            isValid: true,
        });
        this.lastURL = undefined;

        if (this.fieldType === "many2one" && !this.props.previewImage) {
            throw new Error(
                "ImageField: previewImage must be provided when set on a many2one field",
            );
        }
        const field = this.props.record.fields[this.props.name];
        const isDottedRelated = field.related?.includes(".");
        this.uniqueId = this.props.record.data.write_date;
        let resId = this.props.record.resId;
        let value = this.props.record.data[this.props.name];
        const valueChanged = (value, nextValue) =>
            this.fieldType === "many2one"
                ? value?.id !== nextValue?.id ||
                  value?.display_name !== nextValue?.display_name
                : value !== nextValue;
        onWillRender(() => {
            const { record } = this.props;
            const nextValue = record.data[this.props.name];
            if (record.resId !== resId) {
                this.uniqueId = record.data.write_date;
                this.lastURL = undefined;
                this.state.isValid = true;
            } else if (valueChanged(value, nextValue)) {
                this.lastURL = undefined;
                this.state.isValid = true;
                this.uniqueId =
                    isDottedRelated || this.fieldType === "many2one"
                        ? DateTime.now()
                        : record.data.write_date;
            }
            resId = record.resId;
            value = nextValue;
        });
    }

    get imgAlt() {
        if (this.fieldType === "many2one" && this.props.record.data[this.props.name]) {
            return this.props.record.data[this.props.name].display_name;
        }
        return this.props.alt;
    }

    get imgClass() {
        return ["img", "img-fluid", ...this.props.imgClass.split(" ")].join(" ");
    }

    get fieldType() {
        return this.props.record.fields[this.props.name].type;
    }

    get rawCacheKey() {
        return this.uniqueId;
    }

    get sizeStyle() {
        let style = "";
        if (this.props.width) {
            style += `max-width: ${this.props.width}px;`;
            if (!this.props.height) {
                style += `height: auto; max-height: 100%;`;
            }
        }
        if (this.props.height) {
            style += `max-height: ${this.props.height}px;`;
            if (!this.props.width) {
                style += `width: auto; max-width: 100%;`;
            }
        }
        return style;
    }
    get hasTooltip() {
        return this.props.enableZoom && this.props.record.data[this.props.name];
    }
    get tooltipAttributes() {
        const fieldName =
            this.fieldType === "many2one" ? this.props.previewImage : this.props.name;
        return {
            template: "web.ImageZoomTooltip",
            info: JSON.stringify({ url: this.getUrl(fieldName) }),
        };
    }

    getUrl(imageFieldName) {
        if (!this.props.record.data[this.props.name] || !this.state.isValid) {
            return placeholder;
        }
        if (
            !this.props.reload &&
            this.lastURL &&
            this.lastURL.field === imageFieldName
        ) {
            return this.lastURL.url;
        }
        let url;
        if (this.fieldType === "many2one") {
            url = imageUrl(
                this.props.record.fields[this.props.name].relation,
                this.props.record.data[this.props.name].id,
                imageFieldName,
                { unique: this.rawCacheKey },
            );
        } else if (isBinarySize(this.props.record.data[this.props.name])) {
            url = imageUrl(
                this.props.record.resModel,
                this.props.record.resId,
                imageFieldName,
                { unique: this.rawCacheKey },
            );
        } else {
            const magic =
                fileTypeMagicWordMap[this.props.record.data[this.props.name][0]] ||
                "png";
            url = `data:image/${magic};base64,${this.props.record.data[this.props.name]}`;
        }
        this.lastURL = { field: imageFieldName, url };
        return url;
    }
    onFileRemove() {
        this.state.isValid = true;
        this.props.record.update({ [this.props.name]: false });
    }
    async onFileUploaded(info) {
        const record = this.props.record;
        this.state.isValid = true;
        try {
            if (this.props.convertToWebp) {
                info = await convertUploadToWebp(info);
            }
            if (info.type === "image/webp") {
                await createWebpVariantAttachments(this.orm, info);
            }
        } catch (error) {
            if (!(error instanceof ImageDecodeError)) {
                throw error;
            }
            this.notification.add(_t("Could not display the selected image"), {
                type: "danger",
            });
            return;
        }
        if (record !== this.props.record || status(this) === "destroyed") {
            return;
        }
        record.update({ [this.props.name]: info.data });
    }
    onLoadFailed() {
        this.state.isValid = false;
    }
}

export const imageField = {
    component: ImageField,
    displayName: _t("Image"),
    supportedAttributes: [
        {
            label: _t("Alternative text"),
            name: "alt",
            type: "string",
        },
    ],
    supportedOptions: [
        {
            label: _t("Reload"),
            name: "reload",
            type: "boolean",
            default: true,
        },
        {
            label: _t("Enable zoom"),
            name: "zoom",
            type: "boolean",
        },
        {
            label: _t("Convert to webp"),
            name: "convert_to_webp",
            type: "boolean",
        },
        {
            label: _t("Zoom delay"),
            name: "zoom_delay",
            type: "number",
            help: _t(
                "Delay the apparition of the zoomed image with a value in milliseconds",
            ),
        },
        {
            label: _t("Accepted file extensions"),
            name: "accepted_file_extensions",
            type: "string",
        },
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
        {
            label: _t("Preview image"),
            name: "preview_image",
            type: "field",
            availableTypes: ["binary"],
        },
        {
            label: _t("Image class"),
            name: "img_class",
            type: "string",
            help: _t("Extra CSS classes set on the <img> element."),
        },
    ],
    supportedTypes: ["binary", "many2one"],
    fieldDependencies: [{ name: "write_date", type: "datetime" }],
    isEmpty: () => false,
    extractProps: ({ attrs, options }) => ({
        alt: attrs.alt,
        enableZoom: options.zoom,
        convertToWebp: options.convert_to_webp,
        imgClass: options.img_class,
        zoomDelay: options.zoom_delay,
        previewImage: options.preview_image,
        acceptedFileExtensions: options.accepted_file_extensions,
        width: options.size && Boolean(options.size[0]) ? options.size[0] : undefined,
        height: options.size && Boolean(options.size[1]) ? options.size[1] : undefined,
        reload: "reload" in options ? Boolean(options.reload) : true,
    }),
};

registerField("image", /** @type {any} */ (imageField));
