/** @odoo-module native */
import { DEFAULT_PALETTE } from "@html_editor/utils/color";
import { getCSSVariableValue, getHtmlStyle } from "@html_editor/utils/formatting";
import { isSrcCorsProtected } from "@html_editor/utils/image";
import { useRef, useState } from "@odoo/owl";
import { rpc } from "@web/core/network";
import { _t } from "@web/core/translation";
import { KeepLast } from "@web/core/utils/concurrency";

import {
    Attachment,
    FileSelector,
    IMAGE_EXTENSIONS,
    IMAGE_MIMETYPES,
} from "./file_selector.js";

export class AutoResizeImage extends Attachment {
    static template = "html_editor.AutoResizeImage";
    setup() {
        super.setup();

        this.image = useRef("auto-resize-image");
        this.container = useRef("auto-resize-image-container");

        this.state = useState({
            loaded: false,
        });
    }

    async onImageLoaded() {
        if (!this.image.el) {
            return;
        }
        if (this.props.onLoaded) {
            await this.props.onLoaded(this.image.el);
            if (!this.image.el) {
                return;
            }
        }
        const aspectRatio = this.image.el.offsetWidth / this.image.el.offsetHeight;
        const width = aspectRatio * this.props.minRowHeight;
        this.container.el.style.flexGrow = width;
        this.container.el.style.flexBasis = `${width}px`;
        this.state.loaded = true;
    }
}
const newLocal = "img-fluid";
export class ImageSelector extends FileSelector {
    static mediaSpecificClasses = ["img", newLocal, "o_we_custom_image"];
    static mediaSpecificStyles = ["transform", "width"];
    static mediaExtraClasses = [
        "rounded-circle",
        "rounded",
        "img-thumbnail",
        "shadow",
        "w-25",
        "w-50",
        "w-75",
        "w-100",
    ];
    static tagNames = ["IMG"];
    static attachmentsListTemplate = "html_editor.ImagesListTemplate";
    static components = {
        ...FileSelector.components,
        AutoResizeImage,
    };

    setup() {
        super.setup();

        this.keepLastLibraryMedia = new KeepLast();

        this.state.libraryMedia = [];
        this.state.libraryResults = null;
        this.state.isFetchingLibrary = false;
        this.state.searchService = "all";
        this.state.showOptimized = false;
        this.NUMBER_OF_MEDIA_TO_DISPLAY = 10;

        this.uploadText = _t("Upload an image");
        this.urlPlaceholder = "https://www.odoo.com/logo.png";
        this.addText = _t("Add URL");
        this.searchPlaceholder = _t("Search an image");
        this.urlWarningTitle = _t(
            "Uploaded image's format is not supported. Try with: " +
                IMAGE_EXTENSIONS.join(", "),
        );
        this.allLoadedText = _t("All images have been loaded");
        this.showOptimizedOption = this.env.debug;
        this.MIN_ROW_HEIGHT = 128;

        this.fileMimetypes = IMAGE_MIMETYPES.join(",");
        this.isImageField =
            !!this.props.media?.closest("[data-oe-type=image]") ||
            !!this.props.addFieldImage;
        this.isProcessingClick = false;
    }

    get canLoadMore() {
        if (this.state.searchService === "media-library") {
            return (
                this.state.libraryResults &&
                this.state.libraryMedia.length < this.state.libraryResults
            );
        }
        return super.canLoadMore;
    }

    get hasContent() {
        if (this.state.searchService === "all") {
            return super.hasContent || !!this.state.libraryMedia.length;
        } else if (this.state.searchService === "media-library") {
            return !!this.state.libraryMedia.length;
        }
        return super.hasContent;
    }

    get isFetching() {
        return super.isFetching || this.state.isFetchingLibrary;
    }

    get selectedMediaIds() {
        return this.props.selectedMedia[this.props.id]
            .filter((media) => media.mediaType === "libraryMedia")
            .map(({ id }) => id);
    }

    get allAttachments() {
        return [...super.allAttachments, ...this.state.libraryMedia];
    }

    get attachmentsDomain() {
        const domain = super.attachmentsDomain;
        domain.push(["mimetype", "in", IMAGE_MIMETYPES]);
        if (!this.props.useMediaLibrary) {
            domain.push(
                "|",
                ["url", "=", false],
                "!",
                "|",
                ["url", "=ilike", "/html_editor/shape/%"],
                ["url", "=ilike", "/web_editor/shape/%"],
            );
        }
        domain.push("!", ["name", "=like", "%.crop"]);
        domain.push("|", ["type", "=", "binary"], "!", ["url", "=like", "/%/static/%"]);

        if (!this.env.debug) {
            const subDomain = [false];

            const originalId = this.props.media && this.props.media.dataset.originalId;
            if (originalId) {
                subDomain.push(originalId);
            }

            domain.push(["original_id", "in", subDomain]);
        }

        return domain;
    }

    async uploadFiles(files) {
        let abortFn;

        const uploadPromise = this.uploadService.uploadFiles(
            files,
            {
                resModel: this.props.resModel,
                resId: this.props.resId,
                isImage: true,
            },
            (attachment) => this.onUploaded(attachment),
            (abort) => {
                abortFn = abort;
            },
        );
        this.props.setAbortUploadsCallback(() => abortFn?.());
        await uploadPromise;
    }

    async validateUrl(...args) {
        const { isValidUrl, path } = super.validateUrl(...args);
        const isValidFileFormat =
            isValidUrl &&
            (await new Promise((resolve) => {
                const img = new Image();
                img.src = path;
                img.onload = () => resolve(true);
                img.onerror = () => resolve(false);
            }));
        return { isValidFileFormat, isValidUrl };
    }

    async onLoadUploadedUrl(url, resolve) {
        const urlPathname = new URL(url, window.location.href).pathname;
        const imageExtension = IMAGE_EXTENSIONS.find((format) =>
            urlPathname.endsWith(format),
        );
        if (this.isImageField && imageExtension === ".webp") {
            this.notificationService.add(
                _t(
                    "You can not replace a field by this image. If you want to use this image, first save it on your computer and then upload it here.",
                ),
                {
                    type: "danger",
                    sticky: true,
                },
            );
            return resolve();
        }
        super.onLoadUploadedUrl(url, resolve);
    }

    isInitialMedia(attachment) {
        if (this.props.media.dataset.originalSrc) {
            return this.props.media.dataset.originalSrc === attachment.image_src;
        }
        return this.props.media.getAttribute("src") === attachment.image_src;
    }

    async fetchAttachments(limit, offset) {
        const attachments = await super.fetchAttachments(limit, offset);
        if (this.isImageField) {
            for (const attachment of attachments) {
                if (
                    attachment.mimetype === "image/webp" &&
                    (await isSrcCorsProtected(attachment.image_src))
                ) {
                    attachment.unselectable = true;
                }
            }
        }
        const primaryColors = {};
        const htmlStyle = getHtmlStyle(document);
        for (let color = 1; color <= 5; color++) {
            primaryColors[color] = getCSSVariableValue("o-color-" + color, htmlStyle);
        }
        return attachments.map((attachment) => {
            if (attachment.image_src.startsWith("/")) {
                const newURL = new URL(attachment.image_src, window.location.origin);
                if (
                    attachment.image_src.startsWith("/html_editor/shape/") ||
                    attachment.image_src.startsWith("/web_editor/shape/")
                ) {
                    newURL.searchParams.forEach((value, key) => {
                        const match = key.match(/^c([1-5])$/);
                        if (match) {
                            newURL.searchParams.set(key, primaryColors[match[1]]);
                        }
                    });
                } else {
                    newURL.searchParams.set("height", 2 * this.MIN_ROW_HEIGHT);
                }
                attachment.thumbnail_src = newURL.pathname + newURL.search;
            }
            if (this.selectInitialMedia() && this.isInitialMedia(attachment)) {
                this.selectAttachment(attachment);
            }
            return attachment;
        });
    }

    async fetchLibraryMedia(offset) {
        if (!this.state.needle) {
            return { media: [], results: null };
        }

        this.state.isFetchingLibrary = true;
        try {
            const response = await rpc(
                "/html_editor/media_library_search",
                {
                    query: this.state.needle,
                    offset: offset,
                },
                {
                    silent: true,
                },
            );
            this.state.isFetchingLibrary = false;
            const media = (response.media || []).slice(
                0,
                this.NUMBER_OF_MEDIA_TO_DISPLAY,
            );
            media.forEach((record) => (record.mediaType = "libraryMedia"));
            return { media, results: response.results };
        } catch {
            console.error(`Couldn't reach API endpoint.`);
            this.state.isFetchingLibrary = false;
            return { media: [], results: null };
        }
    }

    async loadMore(...args) {
        await super.loadMore(...args);
        if (
            !this.props.useMediaLibrary ||
            this.state.searchService !== "media-library"
        ) {
            return;
        }
        return this.keepLastLibraryMedia
            .add(this.fetchLibraryMedia(this.state.libraryMedia.length))
            .then(({ media }) => {
                this.state.libraryMedia.push(...media);
            });
    }

    async search(...args) {
        await super.search(...args);
        if (!this.props.useMediaLibrary) {
            return;
        }
        if (!this.state.needle) {
            this.state.searchService = "all";
        }
        this.state.libraryMedia = [];
        this.state.libraryResults = 0;
        return this.keepLastLibraryMedia
            .add(this.fetchLibraryMedia(0))
            .then(({ media, results }) => {
                this.state.libraryMedia = media;
                this.state.libraryResults = results;
            });
    }

    async onClickAttachment(attachment) {
        if (this.isProcessingClick) {
            return;
        }
        this.isProcessingClick = true;
        if (attachment.unselectable) {
            this.notificationService.add(
                _t(
                    "You can not replace a field by this image. If you want to use this image, first save it on your computer and then upload it here.",
                ),
                {
                    type: "danger",
                    sticky: true,
                },
            );
            return;
        }
        this.selectAttachment(attachment);
        if (!this.props.multiSelect) {
            await this.props.save();
        }
        requestAnimationFrame(() => {
            this.isProcessingClick = false;
        });
    }

    async onClickMedia(media) {
        this.props.selectMedia({ ...media, mediaType: "libraryMedia" });
        if (!this.props.multiSelect) {
            await this.props.save();
        }
    }

    static async createElements(selectedMedia, { orm }) {
        const toSave = Object.fromEntries(
            selectedMedia
                .filter((media) => media.mediaType === "libraryMedia")
                .map((media) => [
                    media.id,
                    {
                        query: media.query || "",
                        is_dynamic_svg: !!media.isDynamicSVG,
                        dynamic_colors: media.dynamicColors,
                    },
                ]),
        );
        let savedMedia = [];
        if (Object.keys(toSave).length !== 0) {
            savedMedia = await rpc("/html_editor/save_library_media", {
                media: toSave,
            });
        }
        const selected = selectedMedia
            .filter((media) => media.mediaType === "attachment")
            .concat(savedMedia)
            .map((attachment) => {
                if (
                    attachment.image_src &&
                    (attachment.image_src.startsWith("/html_editor/shape/") ||
                        attachment.image_src.startsWith("/web_editor/shape/"))
                ) {
                    const colorCustomizedURL = new URL(
                        attachment.image_src,
                        window.location.origin,
                    );
                    const htmlStyle = getHtmlStyle(document);
                    colorCustomizedURL.searchParams.forEach((value, key) => {
                        const match = key.match(/^c([1-5])$/);
                        if (match) {
                            colorCustomizedURL.searchParams.set(
                                key,
                                getCSSVariableValue(`o-color-${match[1]}`, htmlStyle),
                            );
                        }
                    });
                    attachment.image_src =
                        colorCustomizedURL.pathname + colorCustomizedURL.search;
                }
                return attachment;
            });
        return Promise.all(
            selected.map(async (attachment) => {
                const imageEl = document.createElement("img");
                let src = attachment.image_src;
                if (!attachment.public && !attachment.url) {
                    let accessToken = attachment.access_token;
                    if (!accessToken) {
                        [accessToken] = await orm.call(
                            "ir.attachment",
                            "generate_access_token",
                            [attachment.id],
                        );
                    }
                    src += `?access_token=${encodeURIComponent(accessToken)}`;
                }
                imageEl.src = src;
                imageEl.alt = attachment.description || "";
                imageEl.dataset.attachmentId = attachment.id;
                return imageEl;
            }),
        );
    }

    async onImageLoaded(imgEl, attachment) {
        this.debouncedScrollUpdate();
        if (attachment.mediaType === "libraryMedia" && !imgEl.src.startsWith("blob")) {
            await this.onLibraryImageLoaded(imgEl, attachment);
        }
    }

    /**
     * @param {HTMLElement} imgEl
     * @param {Object} media
     */
    async onLibraryImageLoaded(imgEl, media) {
        const mediaUrl = imgEl.src;
        try {
            const response = await fetch(mediaUrl);
            if (response.headers.get("content-type").startsWith("image/svg+xml")) {
                let svg = await response.text();
                const dynamicColors = {};
                const combinedColorsRegex = new RegExp(
                    Object.values(DEFAULT_PALETTE).join("|"),
                    "gi",
                );
                const htmlStyle = getHtmlStyle(document);
                svg = svg.replace(combinedColorsRegex, (match) => {
                    const colorId = Object.keys(DEFAULT_PALETTE).find(
                        (key) => DEFAULT_PALETTE[key] === match.toUpperCase(),
                    );
                    const colorKey = "c" + colorId;
                    dynamicColors[colorKey] = getCSSVariableValue(
                        "o-color-" + colorId,
                        htmlStyle,
                    );
                    return dynamicColors[colorKey];
                });
                const fileName = mediaUrl.split("/").pop();
                const file = new File([svg], fileName, {
                    type: "image/svg+xml",
                });
                imgEl.src = URL.createObjectURL(file);
                if (Object.keys(dynamicColors).length) {
                    media.isDynamicSVG = true;
                    media.dynamicColors = dynamicColors;
                }
            }
        } catch {
            console.error(
                "CORS is misconfigured on the API server, image will be treated as non-dynamic.",
            );
        }
    }
}
