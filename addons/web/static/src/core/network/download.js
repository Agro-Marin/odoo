// @ts-check
/** @odoo-module native */

import { browser } from "@web/core/browser/browser";
import {
    ConnectionLostError,
    InvalidResponseError,
    makeErrorFromResponse,
} from "@web/core/network/rpc";

import { parse } from "./content_disposition.js";

/**
 * @param {Blob | File | string} data
 * @param {string} [filename]
 * @param {string} [mimetype]
 */
function _download(data, filename, mimetype) {
    if (!filename && !mimetype && typeof data === "string") {
        if (/^data:/i.test(data)) {
            const anchor = document.createElement("a");
            anchor.href = data;
            anchor.download = "download";
            anchor.style.display = "none";
            document.body.appendChild(anchor);
            anchor.click();
            document.body.removeChild(anchor);
            return true;
        }
        const url = data;
        return new Promise((resolve, reject) => {
            const xhr = new browser.XMLHttpRequest();
            xhr.open("GET", url, true);
            configureBlobDownloadXHR(xhr, {
                onSuccess: resolve,
                onFailure: reject,
                url,
            });
            xhr.send();
        });
    }

    const blob =
        data instanceof Blob
            ? data
            : new Blob([data], { type: mimetype || "application/octet-stream" });
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = filename || "download";
    anchor.style.display = "none";
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    browser.setTimeout(() => URL.revokeObjectURL(objectUrl), 250);
    return true;
}

/**
 * @param {string | Blob | File} data
 * @param {String} filename
 * @param {String} mimetype
 * @returns {boolean | Promise<any>}
 */
export function downloadFile(data, filename, mimetype) {
    return downloadFile._download(data, filename, mimetype);
}
downloadFile._download = _download;

/**
 * @param {*} options
 * @returns {Promise<any>}
 */
export function download(options) {
    return download._download(options);
}

download._download = (/** @type {any} */ options) =>
    new Promise((resolve, reject) => {
        const xhr = new browser.XMLHttpRequest();
        let data;
        if (Object.hasOwn(options, "form")) {
            xhr.open(options.form.method, options.form.action);
            data = new FormData(options.form);
        } else {
            xhr.open("POST", options.url);
            data = new FormData();
            for (const [key, value] of Object.entries(options.data || {})) {
                data.append(key, value);
            }
        }
        data.append("token", "dummy-because-api-expects-one");
        if (odoo.csrf_token) {
            data.append("csrf_token", odoo.csrf_token);
        }
        configureBlobDownloadXHR(xhr, {
            onSuccess: resolve,
            onFailure: reject,
            url: options.form?.action ?? options.url,
        });
        xhr.send(data);
    });

/**
 * @param {XMLHttpRequest} xhr
 * @param {object} [options]
 * @param {(filename: string) => void} [options.onSuccess]
 * @param {(error: Error) => void} [options.onFailure]
 * @param {string} [options.url]
 */
function configureBlobDownloadXHR(
    xhr,
    { onSuccess = () => {}, onFailure = () => {}, url } = {},
) {
    xhr.responseType = "blob";
    xhr.onload = () => {
        const mimetype = xhr.response.type;
        const header = (xhr.getResponseHeader("Content-Disposition") || "").replace(
            /;$/,
            "",
        );
        let filename = null;
        if (header) {
            try {
                filename = /** @type {Record<string, any>} */ (parse(header).parameters)
                    .filename;
            } catch {}
        }
        if (xhr.status === 200 && (mimetype !== "text/html" || filename)) {
            const downloadBlob = new Blob([xhr.response], {
                type: "application/octet-stream",
            });
            _download(downloadBlob, filename, "application/octet-stream");
            onSuccess(filename);
        } else if (xhr.status >= 502 && xhr.status <= 504) {
            onFailure(new ConnectionLostError(url));
        } else {
            const decoder = new FileReader();
            decoder.onload = () => {
                const contents = /** @type {string} */ (decoder.result);
                const doc = new DOMParser().parseFromString(contents, "text/html");
                const nodes = !doc.body.children.length
                    ? [doc.body]
                    : doc.body.children;

                let error;
                try {
                    const node = nodes[1] || nodes[0];
                    error = JSON.parse(node.textContent ?? "");
                } catch {
                    if (
                        xhr.status >= 200 &&
                        xhr.status < 300 &&
                        mimetype === "text/html"
                    ) {
                        onFailure(new InvalidResponseError(url ?? "", xhr.status));
                        return;
                    }
                    error = {
                        message: "Arbitrary Uncaught Python Exception",
                        data: {
                            debug:
                                `${xhr.status}` +
                                `\n` +
                                `${nodes.length ? nodes[0].textContent : ""}
                                ${nodes.length > 1 ? nodes[1].textContent : ""}`,
                        },
                    };
                }
                error = makeErrorFromResponse(error);
                onFailure(error);
            };
            const onDecoderFailure = (/** @type {string} */ what) => () =>
                onFailure(
                    new InvalidResponseError(url ?? "", xhr.status, {
                        cause: decoder.error ?? new Error(`FileReader ${what}`),
                    }),
                );
            decoder.onerror = onDecoderFailure("error");
            decoder.onabort = onDecoderFailure("abort");
            decoder.readAsText(xhr.response);
        }
    };
    xhr.onerror = () => {
        onFailure(new ConnectionLostError(url));
    };
}
