/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";

const log = makeLogger("website.content.generate_video_iframe");

const SUPPORTED_DOMAINS = [
    "youtu.be",
    "youtube.com",
    "youtube-nocookie.com",
    "instagram.com",
    "player.vimeo.com",
    "vimeo.com",
    "dailymotion.com",
];

/**
 * @param {HTMLIFrameElement} iframeEl
 * @param {string} src
 */
function manageIframeSrcOnLoad(iframeEl, src) {
    if (!iframeEl.closest("[data-need-cookies-approval]")) {
        iframeEl.setAttribute("src", src);
    } else {
        log.logic("iframe src held until cookies approval", () => ({ src }));
        iframeEl.dataset.nocookieSrc = src;
        iframeEl.setAttribute("src", "about:blank");
        iframeEl.dataset.needCookiesApproval = "true";
    }
}

/**
 * @param {HTMLElement} parentEl
 * @param {function} manageIframeSrcFct
 * @returns {HTMLIframeElement}
 */
export function generateVideoIframe(parentEl, manageIframeSrcFct) {
    parentEl.replaceChildren();

    const extraEditionEl = document.createElement("div");
    extraEditionEl.className = "css_editable_mode_display";
    const extraSizeEl = document.createElement("div");
    extraSizeEl.className = "media_iframe_video_size";
    parentEl.append(extraEditionEl, extraSizeEl);

    const src = parentEl.dataset.oeExpression || parentEl.dataset.src;
    const m = src.match(/^(?:https?:)?\/\/([^/?#]+)/);
    if (!m) {
        log.logic("skip: video src is not an absolute URL", () => ({ src }));
        return;
    }
    const domain = m[1].replace(/^www\./, "");
    if (!SUPPORTED_DOMAINS.includes(domain)) {
        log.logic("skip: unsupported video domain", () => ({ domain }));
        return;
    }
    const iframeEl = document.createElement("iframe");
    iframeEl.setAttribute("frameborder", "0");
    iframeEl.setAttribute("allowfullscreen", "allowfullscreen");
    iframeEl.setAttribute("referrerpolicy", "strict-origin-when-cross-origin");
    parentEl.appendChild(iframeEl);
    log.pipeline("video iframe created", () => ({
        domain,
        customSrcManager: !!manageIframeSrcFct,
    }));
    manageIframeSrcFct
        ? manageIframeSrcFct(iframeEl, src)
        : manageIframeSrcOnLoad(iframeEl, src);

    return iframeEl;
}

document.addEventListener("DOMContentLoaded", () => {
    log.pipeline("DOMContentLoaded video placeholders", () => ({
        placeholders: document.querySelectorAll(".media_iframe_video").length,
    }));
    for (const videoIframeEl of document.querySelectorAll(".media_iframe_video")) {
        if (!videoIframeEl.querySelector(":scope > iframe")) {
            generateVideoIframe(videoIframeEl);
        }
    }
});
