/** @odoo-module native */
import { loadJS } from "@web/core/assets";
import { hasTouch } from "@web/core/browser/feature_detection";
import { SIZES, utils as uiUtils } from "@web/ui/viewport";

/**
 * @param {string} src
 * @param {boolean} needCookiesApproval
 */
export function setupAutoplay(src, needCookiesApproval = false) {
    const isYoutubeVideo = src.indexOf("youtube") >= 0;
    const isMobileEnv = uiUtils.getSize() <= SIZES.LG && hasTouch();

    if (isYoutubeVideo && isMobileEnv && !window.YT && !needCookiesApproval) {
        const oldOnYoutubeIframeAPIReady = window.onYouTubeIframeAPIReady;
        const promise = new Promise((resolve) => {
            window.onYouTubeIframeAPIReady = () => {
                if (oldOnYoutubeIframeAPIReady) {
                    oldOnYoutubeIframeAPIReady();
                }
                return resolve();
            };
        });
        loadJS("https://www.youtube.com/iframe_api");
        return promise;
    }
    return Promise.resolve();
}

/**
 * @param {HTMLIframeElement} iframeEl
 */
export function triggerAutoplay(iframeEl) {
    const isYoutubeVideo = iframeEl.src.indexOf("youtube") >= 0;
    const isMobileEnv = uiUtils.getSize() <= SIZES.LG && hasTouch();

    if (
        isYoutubeVideo &&
        isMobileEnv &&
        iframeEl.closest("[data-need-cookies-approval]")
    ) {
        new window.YT.Player(iframeEl, {
            events: {
                onReady: (ev) => ev.target.playVideo(),
            },
        });
    }
}
