/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { session } from "@web/session";

const ODOO_DOMAIN_REGEX = new RegExp(`^https?://${session.db}\\.odoo\\.com(/.*)?$`);

/**
 * @param {string} url
 * @param {string[]} hostnameList
 * @return {string|boolean}
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
 * @throws {Error}
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
 * @param {string} url
 * @returns {boolean}
 */
export const urlFunctions = {
    isAbsoluteURLInCurrentDomain(url, env = null) {
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
