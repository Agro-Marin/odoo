// @ts-check
/** @odoo-module native */

import { url } from "@web/core/utils/urls";

const IMAGE_MIMETYPES = new Set([
    "image/bmp",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/svg+xml",
    "image/tiff",
    "image/x-icon",
    "image/webp",
]);

const TEXT_MIMETYPES = new Set([
    "application/javascript",
    "application/json",
    "text/css",
    "text/html",
    "text/plain",
]);

const VIDEO_MIMETYPES = new Set([
    "audio/mpeg",
    "video/x-matroska",
    "video/mp4",
    "video/webm",
]);

/**
 * @typedef {Object} FileModelData
 * @property {string} [access_token]
 * @property {string} [checksum]
 * @property {string} [extension]
 * @property {number} [id]
 * @property {string} [mimetype]
 * @property {string} [name]
 * @property {string} [ownership_token]
 * @property {string} [raw_access_token]
 * @property {"binary"|"url"} [type]
 * @property {string} [tmpUrl]
 * @property {string|false|null} [url]
 * @property {boolean} [uploading]
 */

export const FileModelMixin = (T) =>
    class extends T {
        get defaultSource() {
            const route = url(this.urlRoute, this.urlQueryParams);
            const encodedRoute = encodeURIComponent(route);
            if (this.isPdf) {
                return `/web/static/lib/pdfjs/web/viewer.html?file=${encodedRoute}#pagemode=none`;
            }
            const youtubeVideoId = this.youtubeVideoId;
            if (youtubeVideoId) {
                return `https://www.youtube.com/embed/${youtubeVideoId}`;
            }
            return route;
        }

        get downloadUrl() {
            return url(this.urlRoute, {
                ...this.urlQueryParams,
                download: true,
            });
        }

        get isImage() {
            return IMAGE_MIMETYPES.has(this.mimetype);
        }

        get isPdf() {
            return Boolean(
                this.mimetype && this.mimetype.startsWith?.("application/pdf"),
            );
        }

        get isText() {
            return TEXT_MIMETYPES.has(this.mimetype);
        }

        /** @returns {boolean} */
        get isUrl() {
            return this.type === "url" && Boolean(this.url);
        }

        get isUrlYoutube() {
            return Boolean(this.youtubeVideoId);
        }

        /**
         * @returns {string|null}
         */
        get youtubeVideoId() {
            if (typeof this.url !== "string") {
                return null;
            }
            let parsed;
            try {
                parsed = new URL(this.url);
            } catch {
                return null;
            }
            const host = parsed.hostname.replace(/^www\./, "");
            const [prefix, id] = parsed.pathname.split("/").filter(Boolean);
            if (host === "youtu.be") {
                return prefix || null;
            }
            if (host !== "youtube.com" && host !== "youtube-nocookie.com") {
                return null;
            }
            if (parsed.pathname === "/watch") {
                return parsed.searchParams.get("v");
            }
            return ["embed", "shorts", "v"].includes(prefix) ? id || null : null;
        }

        get isVideo() {
            return VIDEO_MIMETYPES.has(this.mimetype);
        }

        get isViewable() {
            return (
                (this.isText ||
                    this.isImage ||
                    this.isVideo ||
                    this.isPdf ||
                    this.isUrlYoutube) &&
                !this.uploading
            );
        }

        /**
         * @returns {Object}
         */
        get urlQueryParams() {
            if (this.uploading && this.tmpUrl) {
                return {};
            }
            const params = {
                access_token: this.raw_access_token || this.access_token,
                filename: this.name,
                unique: this.checksum,
            };
            for (const prop of Object.keys(params)) {
                if (!params[prop]) {
                    delete params[prop];
                }
            }
            return params;
        }

        /**
         * @returns {string}
         */
        get urlRoute() {
            if (this.uploading && this.tmpUrl) {
                return this.tmpUrl;
            }
            return this.isImage ? `/web/image/${this.id}` : `/web/content/${this.id}`;
        }
    };

export class FileModel extends FileModelMixin(Object) {}
