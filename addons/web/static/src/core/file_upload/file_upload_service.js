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
     * @param {string} route
     * @param {FileList | File[]} files
     * @param {{
     * buildFormData?: (formData: FormData) => void,
     * displayErrorNotification?: boolean,
     * [key: string]: any,
     * }} [params]
     */
    async upload(route, files, params = {}) {
        const xhr = fileUploadService.createXhr();
        xhr.open("POST", route);
        const formData = new FormData();
        formData.append("csrf_token", odoo.csrf_token);
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
        xhr.addEventListener("load", () => {
            this.inFlight.delete(xhr);
            try {
                handleResponse();
            } catch (e) {
                onError(e);
                return;
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
         * @returns {true}
         * @throws {Error}
         */
        const handleResponse = () => {
            const resp = xhr.responseText ?? xhr.response;
            let error;
            let errorMessage = "";
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
            return true;
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
