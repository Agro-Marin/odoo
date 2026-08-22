/** @odoo-module native */
import { Cache } from "@web/core/utils/collections/cache";
import { isColorGradient } from "@web/core/utils/format/colors";

const SUPPORTED_MIMETYPES = [
    "image/gif",
    "image/jpe",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/svg+xml",
    "image/webp",
];

const headResponseCache = new Cache(
    async (src) => await fetch(src, { method: "HEAD" }),
    JSON.stringify,
);

const corsProtectedCache = new Cache(
    async (src) =>
        headResponseCache
            .read(src)
            .then(() => false)
            .catch(() => true),
    JSON.stringify,
);

/**
 * @param {string} css
 * @returns {Object}
 */
export function backgroundImageCssToParts(css = "") {
    const parts = {};
    if (css.startsWith("url(")) {
        const urlEnd = css.indexOf(")") + 1;
        parts.url = css.substring(0, urlEnd).trim();
        const commaPos = css.indexOf(",", urlEnd);
        css = commaPos > 0 ? css.substring(commaPos + 1) : "";
    }
    if (isColorGradient(css)) {
        parts.gradient = css.trim();
    }
    return parts;
}

/**
 * @param {Object} parts
 * @returns {string}
 */
export function backgroundImagePartsToCss(parts) {
    return [parts.url, parts.gradient].filter(Boolean).join(", ") || "";
}

/**
 * @param {HTMLImageElement} image
 * @returns {string|null}
 */
export function getMimetype(image, data = image.dataset) {
    const src = getImageSrc(image);

    return (
        data.mimetype ||
        data.mimetypeBeforeConversion ||
        (src &&
            ((src.endsWith(".png") && "image/png") ||
                (src.endsWith(".webp") && "image/webp") ||
                (src.endsWith(".jpg") && "image/jpeg") ||
                (src.endsWith(".jpeg") && "image/jpeg"))) ||
        null
    );
}

/**
 * @param {HTMLImageElement} image
 * @param {Object} data
 * @returns {string|null}
 */
export async function getFetchedMimetype(image, data = image.dataset) {
    const mimetypeOnData = data.mimetype || data.mimetypeBeforeConversion;
    if (mimetypeOnData) {
        return mimetypeOnData;
    }
    const src = getImageSrc(image);
    try {
        const response = await headResponseCache.read(src);
        if (!response.ok) {
            return null;
        }
        const contentType = response.headers.get("content-type");
        if (!SUPPORTED_MIMETYPES.some((mimetype) => contentType.startsWith(mimetype))) {
            return null;
        }
        if (contentType.startsWith("image/svg+xml")) {
            return "image/svg+xml";
        }
        return contentType;
    } catch {
        return null;
    }
}

/**
 * @param {HTMLImageElement} img
 * @returns {Promise<Boolean>}
 */
export async function isImageCorsProtected(img) {
    const src = img.getAttribute("src");
    if (!src) {
        return false;
    }
    let isCorsProtected = false;
    if (!src.startsWith("/") || /\/web\/image\/\d+-redirect\//.test(src)) {
        isCorsProtected = await corsProtectedCache.read(src);
    }
    return isCorsProtected;
}

/**
 * @param {string} src
 * @returns {Promise<Boolean>}
 */
export async function isSrcCorsProtected(src) {
    const dummyImg = document.createElement("img");
    dummyImg.src = src;
    return isImageCorsProtected(dummyImg);
}

/**
 * @param {HTMLElement} el
 * @returns {string|null}
 */
export function getImageSrc(el) {
    if (el.tagName === "IMG") {
        return el.getAttribute("src");
    }
    if (el.querySelector(".s_parallax_bg")) {
        el = el.querySelector(".s_parallax_bg");
    }
    const url = backgroundImageCssToParts(el.style.backgroundImage).url;
    return url && getBgImageURLFromURL(url);
}

/**
 * @param {string} url
 * @returns {string}
 */
export function getBgImageURLFromURL(url) {
    const match = url.match(/^url\((['"])(.*?)\1\)$/);
    if (!match) {
        return "";
    }
    const matchedURL = match[2];
    const fullURL = new URL(matchedURL, window.location.origin);
    if (fullURL.origin === window.location.origin) {
        return fullURL.href.slice(fullURL.origin.length);
    }
    return matchedURL;
}
