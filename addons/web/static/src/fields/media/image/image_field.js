// @ts-check
/** @odoo-module native */

/** @module @web/fields/media/image/image_field - Image upload, preview, and zoom field for Binary image columns */

import { Component, onWillRender, useState } from "@odoo/owl";
import { isMobileOS } from "@web/core/browser/feature_detection";
import { FileUploader } from "@web/core/file_upload/file_handler";
import { DateTime } from "@web/core/l10n/luxon";
import { _t } from "@web/core/l10n/translation";
import { isBinarySize } from "@web/core/utils/format/binary";
import { useService } from "@web/core/utils/hooks";
import { imageUrl } from "@web/core/utils/urls";
import { registerField } from "@web/fields/_registry";
import { standardFieldProps } from "@web/fields/standard_field_props";

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
        // Cache-busting key: write_date snapshotted when the binary value
        // itself (bin_size string or base64 payload) or the record changes.
        // Reading write_date live instead would bust every image URL on any
        // save of any field of the record.
        const field = this.props.record.fields[this.props.name];
        // A dotted related field can change without this record's write_date
        // moving, so bust those with a fresh timestamp instead.
        const isDottedRelated = field.related?.includes(".");
        this.uniqueId = this.props.record.data.write_date;
        let resId = this.props.record.resId;
        let value = this.props.record.data[this.props.name];
        // Many2one values are fresh `{id, display_name}` objects on every
        // record reload: compare by content, not identity, so an unrelated
        // reload doesn't mint a new cache-busting URL and force a refetch.
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
            } else if (valueChanged(value, nextValue)) {
                // A many2one image URL targets the RELATED record, so neither
                // a dotted-related change nor an m2o dialog edit (which only
                // refreshes display_name) moves this record's write_date —
                // the URL would stay byte-identical and serve a stale image,
                // so bust with a fresh timestamp instead.
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
        if (!this.props.reload && this.lastURL) {
            return this.lastURL;
        }
        if (!this.props.record.data[this.props.name] || !this.state.isValid) {
            return placeholder;
        }
        if (this.fieldType === "many2one") {
            this.lastURL = imageUrl(
                this.props.record.fields[this.props.name].relation,
                this.props.record.data[this.props.name].id,
                imageFieldName,
                { unique: this.rawCacheKey },
            );
        } else if (isBinarySize(this.props.record.data[this.props.name])) {
            this.lastURL = imageUrl(
                this.props.record.resModel,
                this.props.record.resId,
                imageFieldName,
                { unique: this.rawCacheKey },
            );
        } else {
            // Use magic-word technique for detecting image type
            const magic =
                fileTypeMagicWordMap[this.props.record.data[this.props.name][0]] ||
                "png";
            this.lastURL = `data:image/${magic};base64,${this.props.record.data[this.props.name]}`;
        }
        return this.lastURL;
    }
    onFileRemove() {
        this.state.isValid = true;
        this.props.record.update({ [this.props.name]: false });
    }
    async onFileUploaded(info) {
        this.state.isValid = true;
        if (
            this.props.convertToWebp &&
            !["image/gif", "image/svg+xml", "image/webp"].includes(info.type)
        ) {
            const image = document.createElement("img");
            image.src = `data:${info.type};base64,${info.data}`;
            try {
                await image.decode();
            } catch {
                // Corrupt/invalid image data: abort the upload instead of
                // hanging forever on a "load" event that never fires.
                this.notification.add(_t("Could not display the selected image"), {
                    type: "danger",
                });
                return;
            }

            const canvas = document.createElement("canvas");
            canvas.width = image.width;
            canvas.height = image.height;
            const ctx = canvas.getContext("2d");
            ctx.drawImage(image, 0, 0);

            const dataURL = canvas.toDataURL("image/webp");
            // Browsers without webp encoding support (e.g. old Safari) fall
            // back to PNG: keep the original format rather than storing
            // PNG bytes labeled as webp.
            if (dataURL.startsWith("data:image/webp")) {
                info.data = dataURL.split(",")[1];
                info.type = "image/webp";
                info.name = info.name.replace(/\.[^/.]+$/, ".webp");
            }
        }
        if (info.type === "image/webp") {
            // Generate alternate sizes and format for reports.
            const image = document.createElement("img");
            image.src = `data:image/webp;base64,${info.data}`;
            try {
                await image.decode();
            } catch {
                // Corrupt/invalid image data: abort the upload instead of
                // hanging forever on a "load" event that never fires.
                this.notification.add(_t("Could not display the selected image"), {
                    type: "danger",
                });
                return;
            }
            const originalSize = Math.max(image.width, image.height);
            // Resized variants need webp re-encoding: skip them on browsers
            // without webp encoding support (the canvas falls back to PNG).
            const canEncodeWebp = document
                .createElement("canvas")
                .toDataURL("image/webp")
                .startsWith("data:image/webp");
            const smallerSizes = canEncodeWebp
                ? [1920, 1024, 512, 256, 128].filter((size) => size < originalSize)
                : [];
            const variants = [originalSize, ...smallerSizes].map((size) => {
                const ratio = size / originalSize;
                const canvas = document.createElement("canvas");
                canvas.width = image.width * ratio;
                canvas.height = image.height * ratio;
                const ctx = canvas.getContext("2d");
                ctx.fillStyle = "transparent";
                ctx.fillRect(0, 0, canvas.width, canvas.height);
                ctx.imageSmoothingEnabled = true;
                ctx.imageSmoothingQuality = "high";
                ctx.drawImage(
                    image,
                    0,
                    0,
                    image.width,
                    image.height,
                    0,
                    0,
                    canvas.width,
                    canvas.height,
                );
                return { size, canvas };
            });
            // The original must be created first: the resized variants
            // reference its id. Batch the rest (create_unique returns ids in
            // input order) instead of two sequential RPCs per size.
            const [originalId] = await this.orm.call("ir.attachment", "create_unique", [
                [
                    {
                        name: info.name,
                        description: "",
                        datas: info.data,
                        res_model: "ir.attachment",
                        mimetype: "image/webp",
                    },
                ],
            ]);
            const resizedVariants = variants.filter(
                ({ size }) => size !== originalSize,
            );
            const resizedIds = resizedVariants.length
                ? await this.orm.call("ir.attachment", "create_unique", [
                      resizedVariants.map(({ size, canvas }) => ({
                          name: info.name,
                          description: `resize: ${size}`,
                          datas: canvas.toDataURL("image/webp").split(",")[1],
                          res_id: originalId,
                          res_model: "ir.attachment",
                          mimetype: "image/webp",
                      })),
                  ])
                : [];
            const idBySize = new Map([
                [originalSize, originalId],
                ...resizedVariants.map(({ size }, index) => [size, resizedIds[index]]),
            ]);
            // Converted to JPEG for use in PDF files, alpha values will default to white
            await this.orm.call("ir.attachment", "create_unique", [
                variants.map(({ size, canvas }) => ({
                    name: info.name.replace(/\.webp$/, ".jpg"),
                    description: "format: jpeg",
                    datas: canvas.toDataURL("image/jpeg").split(",")[1],
                    res_id: idBySize.get(size),
                    res_model: "ir.attachment",
                    mimetype: "image/jpeg",
                })),
            ]);
        }
        this.props.record.update({ [this.props.name]: info.data });
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
