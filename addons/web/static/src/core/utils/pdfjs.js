// @ts-check
/** @odoo-module native */

import { isMobileOS } from "@web/core/browser/feature_detection";
import { makeLazyFacade } from "@web/core/module_bridge";

/**
 * @param {Element} rootElement
 * @param {Object} [options]
 * @param {boolean} [options.hideDownload]
 * @param {boolean} [options.hidePrint]
 * @param {boolean} [options.hidePresentation]
 * @param {boolean} [options.hideRotation]
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
        pendingViewerStyles.set(iframe, cssText);
        if (!iframe.dataset.hideButtons) {
            iframe.dataset.hideButtons = "true";
            iframe.addEventListener("load", () => applyViewerStyle(iframe));
        }
        if (iframe.contentDocument?.readyState === "complete") {
            applyViewerStyle(iframe);
        }
    } else {
        console.warn("No IFRAME found");
    }
}

const VIEWER_STYLE_ID = "o_hide_pdfjs_buttons_style";

/** @type {WeakMap<HTMLIFrameElement, string>} */
const pendingViewerStyles = new WeakMap();

/**
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

/** @type {any} */
let _pdfjsLib = null;

/**
 * @type {any}
 */
export const pdfjsLib = makeLazyFacade(() => _pdfjsLib);

/** @type {Promise<any> | null} */
let loadPromise = null;

/**
 * @returns {Promise<any>}
 */
export async function loadPDFJS() {
    if (!_pdfjsLib) {
        loadPromise ??= (async () => {
            const lib = await import("pdfjs-dist");
            lib.GlobalWorkerOptions.workerSrc =
                "/web/static/lib/pdfjs/build/pdf.worker.js";
            _pdfjsLib = withWasmDefault(lib);
            return pdfjsLib;
        })().catch((error) => {
            loadPromise = null;
            throw error;
        });
        await loadPromise;
    }
    return pdfjsLib;
}

/**
 * @type {string}
 */
const PDFJS_WASM_URL = "/web/static/lib/pdfjs/web/wasm/";

/**
 * A view of pdfjs whose `getDocument` supplies our wasm location by default,
 * leaving every other export resolving live against the library.
 *
 * `lib` is a module namespace: its properties are non-writable, so *assigning*
 * `view.getDocument` throws `TypeError: Cannot assign to property 'getDocument'
 * of [object Module]` -- the prototype's descriptor refuses the write and this
 * module, like every ESM module, is strict. It has to be defined, not assigned.
 *
 * @param {any} lib
 * @returns {any}
 */
export function withWasmDefault(lib) {
    const getDocument = (
        /** @type {string | URL | ArrayBuffer | ArrayBufferView | Record<string, any>} */ src,
    ) => {
        /** @type {Record<string, any>} */
        let params;
        if (typeof src === "string" || src instanceof URL) {
            params = { url: src };
        } else if (src instanceof ArrayBuffer || ArrayBuffer.isView(src)) {
            params = { data: src };
        } else {
            params = { ...src };
        }
        params.wasmUrl ??= PDFJS_WASM_URL;
        return lib.getDocument(params);
    };
    return Object.create(lib, {
        getDocument: {
            configurable: true,
            enumerable: true,
            value: getDocument,
            writable: true,
        },
    });
}
