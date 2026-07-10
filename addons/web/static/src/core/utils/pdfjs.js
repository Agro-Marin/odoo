// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/pdfjs - PDF.js viewer button visibility control and library lazy-loading */

import { isMobileOS } from "@web/core/browser/feature_detection";

/**
 * Until we have our own implementation of the /web/static/lib/pdfjs/web/viewer.{html,js,css}
 * (currently based on Firefox), this method allows us to hide the buttons that we do not want:
 * * All edit buttons
 * * "Open File"
 * * "Current Page" ("#viewBookmark")
 * * "Download" (Hidden on mobile device like Android, iOS, ... or via option)
 * * "Print" (Hidden on mobile device like Android, iOS, ... or via option)
 * * "Presentation" (via options)
 * * "Rotation" (via options)
 *
 * @link https://mozilla.github.io/pdf.js/getting_started/
 *
 * @param {Element} rootElement IFRAME DOM element of PDF.js viewer
 * @param {Object} [options] options to hide additional buttons
 * @param {boolean} [options.hideDownload] hide download button
 * @param {boolean} [options.hidePrint] hide print button
 * @param {boolean} [options.hidePresentation] hide presentation button
 * @param {boolean} [options.hideRotation] hide rotation button
 */
export function hidePDFJSButtons(rootElement, options = {}) {
    const hiddenElements = [
        "#editorModeButtons",
        "button#openFile",
        "button#secondaryOpenFile",
        "a#viewBookmark",
        "a#secondaryViewBookmark",
    ];
    if (options.hideDownload || isMobileOS()) {
        hiddenElements.push("button#downloadButton", "button#secondaryDownload");
    }
    if (options.hidePrint || isMobileOS()) {
        hiddenElements.push("button#printButton", "button#secondaryPrint");
    }
    if (options.hidePresentation) {
        hiddenElements.push("button#presentationMode");
    }
    if (options.hideRotation) {
        hiddenElements.push("button#pageRotateCw");
        hiddenElements.push("button#pageRotateCcw");
    }
    const cssStyle = document.createElement("style");
    cssStyle.textContent = `${hiddenElements.join(", ")} {
    display: none !important;
}`;
    const iframe = /** @type {HTMLIFrameElement | null} */ (
        rootElement.tagName === "IFRAME"
            ? rootElement
            : rootElement.querySelector("iframe")
    );
    if (iframe) {
        if (!iframe.dataset.hideButtons) {
            iframe.dataset.hideButtons = "true";
            iframe.addEventListener("load", (event) => {
                if (iframe.contentDocument && iframe.contentDocument.head) {
                    iframe.contentDocument.head.appendChild(cssStyle);
                }
            });
        }
    } else {
        console.warn("No IFRAME found");
    }
}

/**
 * Live-bound pdf.js namespace (`{ getDocument, GlobalWorkerOptions, ... }`).
 *
 * `null` until {@link loadPDFJS} has resolved at least once; thereafter
 * importers read the loaded namespace through the ES-module live binding.
 * Evaluating the module also assigns `globalThis.pdfjsLib` (a build
 * artifact of the upstream ESM bundle), which the classic
 * `PDFSlidesViewer.js` helper in website_slides still reads.
 *
 * @type {any}
 */
export let pdfjsLib = null;

/** @type {Promise<any> | null} de-dupes concurrent loads into one fetch. */
let loadPromise = null;

/**
 * Lazily load pdf.js, then populate the live-bound {@link pdfjsLib} export.
 *
 * Resolved via the `pdfjs-dist` import-map specifier — replaces the old
 * `loadJS()` + `window.pdfjsLib` pattern, which evaluated the 2.2 MB
 * `pdf.worker.js` on the main thread. `workerSrc` is set centrally so
 * pdf.js spawns its own module worker instead.
 *
 * @returns {Promise<any>} the pdf.js namespace
 */
export async function loadPDFJS() {
    if (!pdfjsLib) {
        loadPromise ??= (async () => {
            const lib = await import("pdfjs-dist");
            lib.GlobalWorkerOptions.workerSrc =
                "/web/static/lib/pdfjs/build/pdf.worker.js";
            pdfjsLib = lib;
            return lib;
        })().catch((error) => {
            // Never cache a rejection: a transient fetch failure would
            // otherwise disable every future PDF preview until a full
            // page reload.
            loadPromise = null;
            throw error;
        });
        await loadPromise;
    }
    return pdfjsLib;
}
