// @ts-check
/** @odoo-module native */

/** @module @web/components/file_viewer/file_model - FileModelMixin providing URL routing and type detection for viewable file attachments */

import { url } from "@web/core/utils/urls";
export const FileModelMixin = (T) =>
    class extends T {
        access_token;
        checksum;
        extension;
        id;
        mimetype;
        name;
        /** @type {string} */
        ownership_token;
        /** @type {string} */
        raw_access_token;
        /** @type {"binary"|"url"} */
        type;
        /** @type {string} */
        tmpUrl;
        /**
         * This URL should not be used as the URL to serve the file. `urlRoute` should be used
         * instead. The server will properly redirect to the correct URL when necessary.
         *
         * @type {string}
         */
        url;
        /** @type {boolean} */
        uploading;

        get defaultSource() {
            const route = url(this.urlRoute, this.urlQueryParams);
            const encodedRoute = encodeURIComponent(route);
            if (this.isPdf) {
                return `/web/static/lib/pdfjs/web/viewer.html?file=${encodedRoute}#pagemode=none`;
            }
            if (this.isUrlYoutube) {
                return `https://www.youtube.com/embed/${this.youtubeVideoId}`;
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
            const imageMimetypes = [
                "image/bmp",
                "image/gif",
                "image/jpeg",
                "image/png",
                "image/svg+xml",
                "image/tiff",
                "image/x-icon",
                "image/webp",
            ];
            return imageMimetypes.includes(this.mimetype);
        }

        get isPdf() {
            return Boolean(
                this.mimetype && this.mimetype.startsWith?.("application/pdf"),
            );
        }

        get isText() {
            const textMimeType = [
                "application/javascript",
                "application/json",
                "text/css",
                "text/html",
                "text/plain",
            ];
            return textMimeType.includes(this.mimetype);
        }

        get isUrl() {
            return this.type === "url" && this.url;
        }

        get isUrlYoutube() {
            return Boolean(this.youtubeVideoId);
        }

        /**
         * Video id when `url` really points at YouTube, `null` otherwise.
         *
         * Matching on the parsed hostname rather than on a `"youtu"` substring:
         * any URL merely containing those letters (`example.com/youtube-clone`)
         * used to be classified as a video and rewritten into an embed of
         * whatever its last path segment happened to be, replacing a working
         * link with a broken player.
         *
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
            const videoMimeTypes = [
                "audio/mpeg",
                "video/x-matroska",
                "video/mp4",
                "video/webm",
            ];
            return videoMimeTypes.includes(this.mimetype);
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
