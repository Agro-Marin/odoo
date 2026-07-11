// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/pdfjs - PDF.js viewer button visibility control and library lazy-loading */

import { isMobileOS } from "@web/core/browser/feature_detection";
import { makeLazyFacade } from "@web/core/module_bridge";

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
    const cssText = `${hiddenElements.join(", ")} {
    display: none !important;
}`;
    const iframe = /** @type {HTMLIFrameElement | null} */ (
        rootElement.tagName === "IFRAME"
            ? rootElement
            : rootElement.querySelector("iframe")
    );
    if (iframe) {
        // Remember the latest requested style so a later call with different
        // options takes effect (the single "load" listener always applies the
        // most recent request instead of the first call's closure).
        pendingViewerStyles.set(iframe, cssText);
        if (!iframe.dataset.hideButtons) {
            iframe.dataset.hideButtons = "true";
            iframe.addEventListener("load", () => applyViewerStyle(iframe));
        }
        // The iframe may already have fired "load" (fast cache, re-mount):
        // apply immediately too. Harmless on a not-yet-navigated document —
        // the "load" listener re-applies into the real viewer document.
        if (iframe.contentDocument?.readyState === "complete") {
            applyViewerStyle(iframe);
        }
    } else {
        console.warn("No IFRAME found");
    }
}

const VIEWER_STYLE_ID = "o_hide_pdfjs_buttons_style";

/** @type {WeakMap<HTMLIFrameElement, string>} latest requested CSS per iframe */
const pendingViewerStyles = new WeakMap();

/**
 * Inject (or update) the button-hiding <style> in the viewer document.
 *
 * @param {HTMLIFrameElement} iframe
 */
function applyViewerStyle(iframe) {
    const doc = iframe.contentDocument;
    if (!doc?.head) {
        return;
    }
    let styleEl = doc.getElementById(VIEWER_STYLE_ID);
    if (!styleEl) {
        styleEl = doc.createElement("style");
        styleEl.id = VIEWER_STYLE_ID;
        doc.head.appendChild(styleEl);
    }
    styleEl.textContent = pendingViewerStyles.get(iframe) ?? "";
}

/** @type {any} the loaded namespace, null until {@link loadPDFJS} resolves */
let _pdfjsLib = null;

/**
 * Stable facade over the lazily-loaded pdf.js namespace
 * (`{ getDocument, GlobalWorkerOptions, ... }`): property reads forward to
 * the loaded namespace, so existing call sites keep working — including
 * through module bridges (iframe bundles), which snapshot exported values
 * and would never see a mutable `export let` reassignment (see the bridge
 * contract in `@web/core/module_bridge`). Callers must still
 * `await loadPDFJS()` before use.
 *
 * Loading the library also assigns `globalThis.pdfjsLib` (a build artifact
 * of the upstream ESM bundle), which the classic `PDFSlidesViewer.js`
 * helper in website_slides still reads.
 *
 * @type {any}
 */
export const pdfjsLib = makeLazyFacade(() => _pdfjsLib);

/** @type {Promise<any> | null} de-dupes concurrent loads into one fetch. */
let loadPromise = null;

/**
 * Lazily load pdf.js, then populate the {@link pdfjsLib} facade.
 *
 * Resolved via the `pdfjs-dist` import-map specifier — replaces the old
 * `loadJS()` + `window.pdfjsLib` pattern, which evaluated the 2.2 MB
 * `pdf.worker.js` on the main thread. `workerSrc` is set centrally so
 * pdf.js spawns its own module worker instead.
 *
 * @returns {Promise<any>} the pdf.js namespace (facade)
 */
export async function loadPDFJS() {
    if (!_pdfjsLib) {
        loadPromise ??= (async () => {
            const lib = await import("pdfjs-dist");
            lib.GlobalWorkerOptions.workerSrc =
                "/web/static/lib/pdfjs/build/pdf.worker.js";
            _pdfjsLib = lib;
            return pdfjsLib;
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
