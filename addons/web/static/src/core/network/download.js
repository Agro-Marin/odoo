// @ts-check
/** @odoo-module native */

/** @module @web/core/network/download - File download via RPC with content-disposition filename extraction */

import { browser } from "@web/core/browser/browser";
import { ConnectionLostError, makeErrorFromResponse } from "@web/core/network/rpc";

import { parse } from "./content_disposition.js";

// -----------------------------------------------------------------------------
// _download — trigger a browser file download from a Blob, data URL, or URL
// -----------------------------------------------------------------------------

/**
 * Trigger a browser file download.
 *
 * Accepts three call patterns:
 *  1. _download(blob, filename)       — download a Blob/File with the given name
 *  2. _download(blob, filename, mime) — same, explicit MIME (used by configureBlobDownloadXHR)
 *  3. _download(url)                  — fetch a same-origin URL as a blob and download it
 *
 * @param {Blob | File | string} data
 * @param {string} [filename]
 * @param {string} [mimetype]
 */
function _download(data, filename, mimetype) {
    // Pattern 3: single URL argument — fetch via XHR and hand off to configureBlobDownloadXHR
    if (!filename && !mimetype && typeof data === "string") {
        // Data URLs can be downloaded directly via an anchor click.
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

    // Pattern 1 & 2: Blob/File download via <a download> click
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
    // Delay revocation so the browser has time to start the download.
    setTimeout(() => URL.revokeObjectURL(objectUrl), 250);
    return true;
}

// -----------------------------------------------------------------------------
// Exported download functions
// -----------------------------------------------------------------------------

/**
 * Download data as a file.
 *
 * @param {string | Blob | File} data
 * @param {String} filename
 * @param {String} mimetype
 * @returns {boolean | Promise<any>}
 *
 * The indirection through ``downloadFile._download`` exists so tests can
 * patch the implementation (``_download`` returns ``Promise<any>``; test
 * patches historically return ``true``).
 */
export function downloadFile(data, filename, mimetype) {
    return downloadFile._download(data, filename, mimetype);
}
downloadFile._download = _download;

/**
 * Call a controller with some data (from a form or a server url) and download
 * the response.
 *
 * Indirection through ``download._download`` exists so tests can patch it.
 *
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
            // The `form` call pattern has no options.url; the request target is
            // the form's action. Fall back to it so ConnectionLostError carries
            // the real URL instead of `undefined`.
            url: options.form?.action ?? options.url,
        });
        xhr.send(data);
    });

/**
 * Setup a download xhr request response handling
 * (onload, onerror, responseType), with hooks when the download succeeds or
 * fails.
 *
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
        // replace because apparently we send some C-D headers with a trailing ";"
        let filename = null;
        if (header) {
            try {
                filename = /** @type {Record<string, any>} */ (parse(header).parameters)
                    .filename;
            } catch {
                // Malformed Content-Disposition — fall back to no filename.
            }
        }
        // Odoo's default mimetype, including for JSON errors, is text/html
        // (ref: http.py:Root.get_response); requiring a filename too lets us
        // still support downloading actual HTML files.
        if (xhr.status === 200 && (mimetype !== "text/html" || filename)) {
            // Repackage as application/octet-stream so browsers (Safari, Chrome) do not
            // intercept the blob URL with their built-in PDF/office viewers and open it
            // inline instead of downloading. The filename extension is sufficient for the
            // OS to restore the correct file type after download.
            const downloadBlob = new Blob([xhr.response], {
                type: "application/octet-stream",
            });
            _download(downloadBlob, filename, "application/octet-stream");
            onSuccess(filename);
        } else if (xhr.status >= 502 && xhr.status <= 504) {
            // Bad Gateway (502) / Service Unavailable (503) / Gateway Timeout
            // (504): Odoo is behind another server (nginx) that could not reach
            // it. Surface a ConnectionLostError instead of trying to parse the
            // proxy's raw HTML error page. Matches rpc.js's status handling.
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
                    // a Serialized python Error
                    const node = nodes[1] || nodes[0];
                    error = JSON.parse(node.textContent);
                } catch {
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
            decoder.readAsText(xhr.response);
        }
    };
    xhr.onerror = () => {
        onFailure(new ConnectionLostError(url));
    };
}
