/** @odoo-module native */
import { loadBundle } from "@web/core/assets";
import { rpc } from "@web/core/network";
import { pick } from "@web/core/utils/collections/objects";

import { getImageSrc } from "./image.js";

export const cropperDataFields = [
    "x",
    "y",
    "width",
    "height",
    "rotate",
    "scaleX",
    "scaleY",
];
export const cropperDataFieldsWithAspectRatio = [...cropperDataFields, "aspectRatio"];
export const isGif = (mimetype) => mimetype === "image/gif";

let _isWebGLEnabled;
export function isWebGLEnabled() {
    if (_isWebGLEnabled !== undefined) {
        return _isWebGLEnabled;
    }
    try {
        const canvas = document.createElement("canvas");
        _isWebGLEnabled = !!(
            window.WebGLRenderingContext &&
            (canvas.getContext("webgl") || canvas.getContext("experimental-webgl"))
        );
    } catch {
        _isWebGLEnabled = false;
    }
    return _isWebGLEnabled;
}

const modifierFields = [
    "filter",
    "quality",
    "mimetype",
    "glFilter",
    "originalId",
    "originalSrc",
    "resizeWidth",
    "aspectRatio",
    "mimetypeBeforeConversion",
];

export const removeOnImageChangeAttrs = [...cropperDataFields, ...modifierFields];

const cache = {};

const placeholderHref = "/web/image/__odoo__unknown__src__/";

function _getValidSrc(src) {
    if (src in cache) {
        return cache[src];
    }
    const prom = new Promise((resolve) => {
        fetch(src)
            .then((response) => {
                resolve(response.ok ? src : placeholderHref);
            })
            .catch(() => {
                resolve(placeholderHref);
            });
    });
    cache[src] = prom;
    return prom;
}

/**
 * @param {String} src
 * @param {HTMLImageElement} [img]
 * @returns {Promise<HTMLImageElement>}
 */
export async function loadImage(src, img = new Image()) {
    const source = await _getValidSrc(src);
    return new Promise((resolve, reject) => {
        img.addEventListener("load", () => resolve(img), { once: true });
        img.addEventListener("error", reject, { once: true });
        img.src = source;
    });
}

const imageCache = new Map();

/**
 * @param {String} src
 * @returns {Promise}
 */
function _loadImageObjectURL(src) {
    return _updateImageData(src);
}

/**
 * @param {String} src
 * @returns {Promise}
 */
export function loadImageDataURL(src) {
    return _updateImageData(src, "dataURL");
}

/**
 * @param {String} src
 * @param {String} [key='objectURL']
 * @returns {Promise<String>}
 */
async function _updateImageData(src, key = "objectURL") {
    const currentImageData = imageCache.get(src);
    if (currentImageData && currentImageData[key]) {
        return currentImageData[key];
    }
    let value;
    const blob = await fetch(src).then((res) => res.blob());
    if (key === "dataURL") {
        value = await createDataURL(blob);
    } else {
        value = URL.createObjectURL(blob);
    }
    imageCache.set(
        src,
        Object.assign(currentImageData || {}, { [key]: value, size: blob.size }),
    );
    return value;
}

/**
 * @param {String} src
 * @returns {Number}
 */
export function getImageSizeFromCache(src) {
    return imageCache.get(src).size;
}

/**
 * @param {HTMLImageElement} image
 * @param {Number} aspectRatio
 * @param {DOMStringMap} dataset
 */
export async function activateCropper(image, aspectRatio, dataset, { onReady } = {}) {
    await loadBundle("html_editor.assets_image_cropper");
    const oldSrc = image.src;
    const newSrc = await _loadImageObjectURL(image.getAttribute("src"));
    image.src = newSrc;
    let readyResolve;
    const readyPromise = new Promise((resolve) => (readyResolve = resolve));
    // eslint-disable-next-line no-undef
    const cropper = new Cropper(image, {
        viewMode: 2,
        dragMode: "move",
        autoCropArea: 1.0,
        aspectRatio: aspectRatio,
        data: Object.fromEntries(
            Object.entries(pick(dataset, ...cropperDataFields)).map(([key, value]) => [
                key,
                parseFloat(value),
            ]),
        ),
        minContainerWidth: 1,
        minContainerHeight: 1,
        ready: () => {
            readyResolve();
            if (onReady) {
                onReady(cropper);
            }
        },
    });
    if (oldSrc === newSrc && image.complete) {
        return;
    }
    await readyPromise;
    return cropper;
}

/**
 * @param {HTMLElement} el
 * @param {string} [attachmentSrc='']
 */
export async function loadImageInfo(el, attachmentSrc = "") {
    const newDataset = {};
    const elSrc = getImageSrc(el);

    const src = attachmentSrc || elSrc;
    if ((el.dataset.originalSrc && el.dataset.mimetypeBeforeConversion) || !src) {
        return newDataset;
    }
    let docHref = el.ownerDocument.defaultView.location.href;
    if (docHref.startsWith("about:")) {
        docHref = window.location.href;
    }

    const srcUrl = new URL(src, docHref);
    let relativeSrc = decodeURI(srcUrl.pathname);

    let match = relativeSrc.match(
        /\/(?:web_editor|html_editor)\/image_shape\/(\w+\.\w+)/,
    );
    if (el.dataset.shape && match) {
        match = match[1];
        if (match.endsWith("_perspective")) {
            match = match.slice(0, -12);
        }
        relativeSrc = `/web/image/${encodeURIComponent(match)}`;
    }

    const { original } = await rpc(
        "/html_editor/get_image_info",
        { src: relativeSrc },
        { cache: true },
    );
    if (
        original &&
        original.image_src &&
        !/\/web\/image\/\d+-redirect\//.test(original.image_src)
    ) {
        newDataset.originalId = original.id;
        newDataset.originalSrc = original.image_src;
        newDataset.mimetypeBeforeConversion = original.mimetype;
    }
    return newDataset;
}

/**
 * @param {Blob} blob
 * @returns {Promise}
 */
export function createDataURL(blob) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.addEventListener("load", () => resolve(reader.result));
        reader.addEventListener("abort", reject);
        reader.addEventListener("error", reject);
        reader.readAsDataURL(blob);
    });
}

/**
 * @param {String} dataURL
 * @returns {Number}
 */
export function getDataURLBinarySize(dataURL) {
    return (dataURL.split(",")[1].length / 4) * 3;
}

/**
 * @param {string|number} ratio
 * @returns {number}
 */
export function getAspectRatio(ratio) {
    if (typeof ratio === "number") {
        return ratio;
    }
    const [a, b] = ratio.split(/[:/]/).map((n) => parseFloat(n));
    if (!b) {
        return a;
    }
    return a / b;
}
