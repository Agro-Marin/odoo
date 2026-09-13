/** @odoo-module native */
import { loadJS } from "@web/core/assets";
import { hasTouch } from "@web/core/browser/feature_detection";
import { makeLogger } from "@web/core/debug/debug_logger";
import { SIZES, utils as uiUtils } from "@web/ui/viewport";

const log = makeLogger("website.utils.videos");

/**
 * @param {string} src
 * @param {boolean} needCookiesApproval
 */
export function setupAutoplay(src, needCookiesApproval = false) {
    const isYoutubeVideo = src.indexOf("youtube") >= 0;
    const isMobileEnv = uiUtils.getSize() <= SIZES.LG && hasTouch();

    log.logic("setupAutoplay", () => ({
        isYoutubeVideo,
        isMobileEnv,
        hasYT: !!window.YT,
        needCookiesApproval,
    }));
    if (isYoutubeVideo && isMobileEnv && !window.YT && !needCookiesApproval) {
        log.pipeline("setupAutoplay: loading youtube iframe api");
        const oldOnYoutubeIframeAPIReady = window.onYouTubeIframeAPIReady;
        const promise = new Promise((resolve) => {
            window.onYouTubeIframeAPIReady = () => {
                log.lifecycle("youtube iframe api ready", () => ({
                    chained: !!oldOnYoutubeIframeAPIReady,
                }));
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
        log.lifecycle("triggerAutoplay: creating YT player", () => ({
            src: iframeEl.src,
        }));
        new window.YT.Player(iframeEl, {
            events: {
                onReady: (ev) => ev.target.playVideo(),
            },
        });
    }
}
