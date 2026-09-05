// @ts-check
/** @odoo-module native */

import { EventBus, reactive } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { FileUploadEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";

class FileUploadService {
    /**
     * @param {{ notification: any }} services
     */
    constructor({ notification: notificationService }) {
        this.notificationService = notificationService;
        /** @type {Record<number, Object>} */
        this.uploads = reactive({});
        this.nextId = 1;
        this.bus = new EventBus();
        /** @type {Set<XMLHttpRequest>} */
        this.inFlight = new Set();
        this.destroyed = false;
    }

    /**
     * An empty stand-in that keeps the file's identity, so a controller can
     * create the record and sign a direct upload for it without the bytes.
     *
     * @param {File} file
     * @returns {File}
     */
    placeholderFor(file) {
        return new File([new Blob([])], file.name, { type: file.type });
    }

    /**
     * @param {string} route
     * @param {FileList | File[]} files
     * @param {{
     * buildFormData?: (formData: FormData) => void,
     * displayErrorNotification?: boolean,
     * directFile?: File,
     * [key: string]: any,
     * }} [params] `directFile` makes the upload two-phase: the route
     *  receives an empty placeholder carrying the file's name and type and
     *  must answer with an `upload_info`; the real bytes then go straight to
     *  that URL, and LOADED fires only once both phases have succeeded.
     */
    async upload(route, files, params = {}) {
        const xhr = fileUploadService.createXhr();
        xhr.open("POST", route);
        const formData = new FormData();
        formData.append("csrf_token", odoo.csrf_token);
        if (params.directFile) {
            files = [this.placeholderFor(params.directFile)];
        }
        for (const file of files) {
            formData.append("ufile", file);
        }
        if (params.buildFormData) {
            params.buildFormData(formData);
        }
        const upload = reactive({
            id: this.nextId++,
            xhr,
            data: formData,
            progress: 0,
            loaded: 0,
            total: 0,
            state: "pending",
            title: files.length === 1 ? files[0].name : _t("%s Files", files.length),
            type: files.length === 1 ? files[0].type : undefined,
        });
        this.uploads[upload.id] = upload;
        xhr.upload.addEventListener("progress", (ev) => {
            upload.progress = ev.total > 0 ? ev.loaded / ev.total : 0;
            upload.loaded = ev.loaded;
            upload.total = ev.total;
            upload.state = "loading";
        });
        xhr.addEventListener("load", async () => {
            this.inFlight.delete(xhr);
            let content;
            try {
                content = handleResponse();
            } catch (e) {
                onError(e);
                return;
            }
            if (params.directFile) {
                if (!content?.upload_info) {
                    onError(
                        new Error(_t("The server did not return a direct upload URL.")),
                    );
                    return;
                }
                upload.state = "loading";
                try {
                    await this.uploadToUrl(content.upload_info, params.directFile, {
                        onProgress: (loaded, total) => {
                            upload.progress = total > 0 ? loaded / total : 0;
                            upload.loaded = loaded;
                            upload.total = total;
                        },
                    });
                } catch (e) {
                    onError(e);
                    return;
                }
            }
            delete this.uploads[upload.id];
            upload.state = "loaded";
            this.bus.trigger(FileUploadEvent.LOADED, { upload });
        });

        /**
         * @returns {boolean}
         */
        const wasRedirected = () => {
            const finalUrl = xhr.responseURL;
            if (!finalUrl) {
                return false;
            }
            try {
                const base = browser.location.href;
                return (
                    new URL(finalUrl, base).pathname !== new URL(route, base).pathname
                );
            } catch {
                return false;
            }
        };

        /**
         * @returns {Object|undefined} the parsed JSON body, when it is one
         * @throws {Error}
         */
        const handleResponse = () => {
            const resp = xhr.responseText ?? xhr.response;
            let error;
            let errorMessage = "";
            let parsed;
            if (!(xhr.status >= 200 && xhr.status < 300)) {
                error = true;
            }
            if (!error && wasRedirected()) {
                error = true;
                errorMessage = _t("Your session expired. Please log in again.");
            }
            if (resp) {
                let content = resp;
                if (typeof content === "string") {
                    try {
                        content = JSON.parse(content);
                    } catch {
                        try {
                            content = new DOMParser().parseFromString(
                                content,
                                "text/html",
                            );
                        } catch {}
                    }
                }
                if (error && content instanceof Document) {
                    errorMessage = content.body?.textContent?.trim() || errorMessage;
                } else if (content instanceof Object) {
                    parsed = content;
                    if (content.error) {
                        error = true;
                        if (content.error.data) {
                            errorMessage = `${content.error.data.name}: ${content.error.data.message}`;
                        } else {
                            errorMessage = content.error.message || errorMessage;
                        }
                    }
                }
            }
            if (error) {
                throw new Error(errorMessage);
            }
            return parsed;
        };

        /**
         * @param {Error} [error]
         */
        const onError = (error) => {
            const defaultErrorMessage = _t("An error occurred while uploading.");
            this.inFlight.delete(xhr);
            delete this.uploads[upload.id];
            upload.state = "error";
            const displayError =
                !this.destroyed && (params.displayErrorNotification ?? true);
            if (displayError) {
                this.notificationService.add(error?.message || defaultErrorMessage, {
                    type: "danger",
                    sticky: true,
                });
            }
            this.bus.trigger(FileUploadEvent.ERROR, { upload });
        };
        xhr.addEventListener("error", () => onError());
        xhr.addEventListener("abort", () => {
            this.inFlight.delete(xhr);
            delete this.uploads[upload.id];
            upload.state = "abort";
            this.bus.trigger(FileUploadEvent.ERROR, { upload });
        });
        this.inFlight.add(xhr);
        xhr.send(formData);
        this.bus.trigger(FileUploadEvent.ADDED, { upload });
        return upload;
    }

    /**
     * Send a file's bytes straight to a storage URL a controller signed for
     * it, outside the Odoo server. Resolves on the status the signer declared
     * and rejects with an Error carrying `status` otherwise; the browser
     * reports a CORS refusal as a network error, which arrives as status 0.
     *
     * @param {{url: string, method: string, response_status: number, headers?: Record<string, string>}} uploadInfo
     * @param {File | Blob} file
     * @param {{ onProgress?: (loaded: number, total: number) => void }} [options]
     * @returns {Promise<XMLHttpRequest> & { abort: () => void }}
     */
    uploadToUrl(uploadInfo, file, { onProgress } = {}) {
        const xhr = fileUploadService.createXhr();
        this.inFlight.add(xhr);
        const promise = new Promise((resolve, reject) => {
            const fail = (message, status) => {
                this.inFlight.delete(xhr);
                const error = new Error(message);
                error.status = status;
                reject(error);
            };
            xhr.open(uploadInfo.method, uploadInfo.url);
            for (const [key, value] of Object.entries(uploadInfo.headers || {})) {
                xhr.setRequestHeader(key, value);
            }
            if (onProgress) {
                xhr.upload.addEventListener("progress", (ev) =>
                    onProgress(ev.loaded, ev.total),
                );
            }
            xhr.addEventListener("load", () => {
                if (xhr.status === 403) {
                    fail(
                        _t("You are not allowed to upload file to the cloud storage"),
                        403,
                    );
                } else if (xhr.status !== uploadInfo.response_status) {
                    fail(_t("Cloud storage error"), xhr.status);
                } else {
                    this.inFlight.delete(xhr);
                    resolve(xhr);
                }
            });
            xhr.addEventListener("error", () => fail(_t("Cloud storage error"), 0));
            xhr.addEventListener("abort", () => {
                const error = new Error(_t("Upload aborted"));
                error.name = "AbortError";
                this.inFlight.delete(xhr);
                reject(error);
            });
            xhr.send(file);
        });
        return Object.assign(promise, { abort: () => xhr.abort() });
    }

    destroy() {
        this.destroyed = true;
        for (const xhr of [...this.inFlight]) {
            this.inFlight.delete(xhr);
            xhr.abort();
        }
    }
}

export const fileUploadService = {
    dependencies: ["notification"],
    async: ["upload"],
    /**
     * @private
     * @returns {XMLHttpRequest}
     */
    createXhr() {
        return new browser.XMLHttpRequest();
    },

    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ notification: any }} services
     * @returns {FileUploadService}
     */
    start(env, services) {
        return new FileUploadService(services);
    },
};

registry.category("services").add("file_upload", fileUploadService);
