/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { session } from "@web/session";

const ODOO_DOMAIN_REGEX = new RegExp(`^https?://${session.db}\\.odoo\\.com(/.*)?$`);

/**
 * If the given URL's hostname is one of the allowed hostnames, returns the URL
 * rebuilt as https://<hostname><pathname>; otherwise returns false.
 *
 * @param {string} url - The URL to check
 * @param {string[]} hostnameList - The list of allowed hostnames
 * @return {string|boolean} The rebuilt URL, or false if the hostname is not allowed
 */
export function checkURL(url, hostnameList) {
    if (url) {
        let potentialURL;
        try {
            potentialURL = new URL(url);
        } catch {
            return false;
        }
        if (hostnameList.includes(potentialURL.hostname)) {
            return `https://${potentialURL.hostname}${potentialURL.pathname}`;
        }
    }
    return false;
}

/**
 * @param {string} url
 */
export function isImageUrl(url) {
    const urlFileExtention = url.split(".").pop();
    return ["jpg", "jpeg", "png", "gif", "svg", "webp"].includes(
        urlFileExtention.toLowerCase(),
    );
}

/**
 * @param {string} platform
 * @param {string} videoId
 * @param {Object} params
 * @throws {Error} if the given video config is not recognized
 * @returns {URL}
 */
export function getVideoUrl(platform, videoId, params) {
    let url;
    switch (platform) {
        case "youtube":
            url = new URL(`https://www.youtube.com/embed/${videoId}`);
            break;
        case "vimeo":
            url = new URL(`https://player.vimeo.com/video/${videoId}`);
            break;
        case "dailymotion":
            url = new URL(`https://www.dailymotion.com/embed/video/${videoId}`);
            break;
        case "instagram":
            url = new URL(`https://www.instagram.com/p/${videoId}/embed`);
            break;
        default:
            throw new Error(`Unsupported platform: ${platform}`);
    }
    url.search = new URLSearchParams(params);
    return url;
}

/**
 * Checks if the given URL is using the domain where the content being
 * edited is reachable, i.e. if this URL should be stripped of its domain
 * part and converted to a relative URL if put as a link in the content.
 *
 * @param {string} url
 * @returns {boolean}
 */
// Patchable object for functions that need to be extended by other modules.
// ESM namespace objects are non-configurable, so patch() cannot redefine
// their properties. This object provides a patchable indirection layer.
// The exported functions below delegate to this object, so patching it
// affects ALL consumers — even those using direct named imports.
export const urlFunctions = {
    isAbsoluteURLInCurrentDomain(url, env = null) {
        // First check if it is a relative URL: if it is, we don't want to check
        // further as we will always leave those untouched.
        let hasProtocol;
        try {
            hasProtocol = !!new URL(url).protocol;
        } catch {
            hasProtocol = false;
        }
        if (!hasProtocol) {
            return false;
        }

        const urlObj = new URL(url, window.location.origin);
        return (
            urlObj.origin === window.location.origin ||
            ODOO_DOMAIN_REGEX.test(urlObj.origin)
        );
    },
};

export function isAbsoluteURLInCurrentDomain(url, env = null) {
    return urlFunctions.isAbsoluteURLInCurrentDomain(url, env);
}

export function scrollAndHighlightHeading(
    content,
    headingId = browser?.location?.hash?.replace?.(/^#/, ""),
) {
    if (content && headingId) {
        // Wait until the browser has rendered the editor before
        // scrolling. The timeout value of 500 is a little arbitrary,
        // but it should be enough to prevent an irritating case where
        // a Youtube video is in the document and loads while the
        // autoscroll is happening, and stops it.
        setTimeout(() => {
            const heading = content.querySelector(
                `[data-heading-link-id="${headingId}"]`,
            );
            if (heading) {
                heading.scrollIntoView({ behavior: "smooth" });
                heading.classList.add("o-highlight-heading");
                setTimeout(() => {
                    heading.classList.remove("o-highlight-heading");
                }, 2000);
            }
        }, 500);
    }
}
