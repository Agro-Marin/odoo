// @ts-check
/** @odoo-module native */

import { onWillRender, status, useState } from "@odoo/owl";
import { isMobileOS } from "@web/core/browser/feature_detection";
import { FileUploader } from "@web/core/file_upload/file_handler";
import { DateTime } from "@web/core/l10n/luxon";
import { _t } from "@web/core/translation";
import { isBinarySize } from "@web/core/utils/format/binary";
import { useService } from "@web/core/utils/hooks";
import { imageUrl } from "@web/core/utils/urls";
import { registerField } from "@web/fields/_registry";
import { FieldComponent } from "@web/fields/field_component";
import { fieldHandleFor } from "@web/fields/field_handle";
import {
    acceptedFileExtensionsOption,
    imageSizeOption,
} from "@web/fields/field_options";
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

export class ImageField extends FieldComponent {
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
    /**
     * @type {Map<string, string>}
     */
    urlCache;

    setup() {
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.isMobile = isMobileOS();
        this.state = useState({
            isValid: true,
        });
        this.urlCache = new Map();

        if (this.fieldType === "many2one" && !this.props.previewImage) {
            throw new Error(
                "ImageField: previewImage must be provided when set on a many2one field",
            );
        }
        const field = this.field.definition;
        const isDottedRelated = field.related?.includes(".");
        this.uniqueId = this.props.record.data.write_date;
        let resId = this.props.record.resId;
        let value = this.field.value;
        const valueChanged = (value, nextValue) =>
            this.fieldType === "many2one"
                ? value?.id !== nextValue?.id ||
                  value?.display_name !== nextValue?.display_name
                : value !== nextValue;
        onWillRender(() => {
            const { record } = this.props;
            const nextValue = fieldHandleFor(record, this.props.name).value;
            if (record.resId !== resId) {
                this.uniqueId = record.data.write_date;
                this.urlCache.clear();
                this.state.isValid = true;
            } else if (valueChanged(value, nextValue)) {
                this.urlCache.clear();
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
        if (this.fieldType === "many2one" && this.field.value) {
            return this.field.value.display_name;
        }
        return this.props.alt;
    }

    get imgClass() {
        return ["img", "img-fluid", ...this.props.imgClass.split(" ")]
            .filter(Boolean)
            .join(" ");
    }

    get fieldType() {
        return this.field.type;
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
        return this.props.enableZoom && this.field.value;
    }
    /**
     * @returns {Record<string, string>}
     */
    get tooltipAttributes() {
        if (!this.hasTooltip) {
            return {};
        }
        const fieldName =
            this.fieldType === "many2one" ? this.props.previewImage : this.props.name;
        return {
            "data-tooltip-template": "web.ImageZoomTooltip",
            "data-tooltip-info": JSON.stringify({ url: this.getUrl(fieldName) }),
            ...(this.props.zoomDelay
                ? { "data-tooltip-delay": String(this.props.zoomDelay) }
                : {}),
        };
    }

    getUrl(imageFieldName) {
        if (!this.field.value || !this.state.isValid) {
            return placeholder;
        }
        if (!this.props.reload && this.urlCache.has(imageFieldName)) {
            return /** @type {string} */ (this.urlCache.get(imageFieldName));
        }
        let url;
        if (this.fieldType === "many2one") {
            url = imageUrl(
                this.field.definition.relation,
                this.field.value.id,
                imageFieldName,
                { unique: this.rawCacheKey },
            );
        } else if (isBinarySize(this.field.value)) {
            url = imageUrl(
                this.props.record.resModel,
                this.props.record.resId,
                imageFieldName,
                { unique: this.rawCacheKey },
            );
        } else {
            const magic = fileTypeMagicWordMap[this.field.value[0]] || "png";
            url = `data:image/${magic};base64,${this.field.value}`;
        }
        this.urlCache.set(imageFieldName, url);
        return url;
    }
    onFileRemove() {
        this.state.isValid = true;
        this.field.update(false);
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
        this.field.update(info.data);
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
        acceptedFileExtensionsOption(),
        imageSizeOption(),
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
