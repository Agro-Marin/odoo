// @ts-check
/** @odoo-module native */

import { browser } from "./browser.js";

/** @type {string | undefined} */
let _cachedUA;

/** @type {ReturnType<typeof _computeUAResults> | undefined} */
let _uaResults;

/**
 * @param {string} ua
 */
function _computeUAResults(ua) {
    const chrome = /Chrome/i.test(ua);
    return {
        chrome,
        firefox: /Firefox/i.test(ua),
        edge: /Edg/i.test(ua),
        safari:
            !chrome && !/(CriOS|FxiOS|EdgiOS|OPiOS)/i.test(ua) && ua.includes("Safari"),
        android: /Android/i.test(ua),
        iosUA: /(iPad|iPhone|iPod)/i.test(ua),
        otherMobile: /(webOS|BlackBerry|Windows Phone)/i.test(ua),
        mac: /Mac/i.test(ua),
        iosApp: /OdooMobile \(iOS\)/i.test(ua),
        androidApp: /OdooMobile.+Android/i.test(ua),
    };
}

function _getUA() {
    const ua = browser.navigator.userAgent || "";
    if (ua !== _cachedUA) {
        _cachedUA = ua;
        _uaResults = _computeUAResults(ua);
    }
    return /** @type {NonNullable<typeof _uaResults>} */ (_uaResults);
}

/**
 * @returns {boolean}
 */
export function isBrowserChrome() {
    return _getUA().chrome;
}

/**
 * @returns {boolean}
 */
export function isBrowserFirefox() {
    return _getUA().firefox;
}

/**
 * @returns {boolean}
 */
export function isBrowserMicrosoftEdge() {
    return _getUA().edge;
}

/**
 * @returns {boolean}
 */
export function isBrowserSafari() {
    return _getUA().safari;
}

/**
 * @returns {boolean}
 */
export function isAndroid() {
    return _getUA().android;
}

/**
 * @returns {boolean}
 */
export function isIOS() {
    if (_getUA().iosUA) {
        return true;
    }
    if ("platform" in browser.navigator) {
        return browser.navigator.platform === "MacIntel" && maxTouchPoints() > 1;
    }
    return false;
}

/**
 * @returns {boolean}
 */
export function isOtherMobileOS() {
    return _getUA().otherMobile;
}

/**
 * @returns {boolean}
 */
export function isMacOS() {
    return _getUA().mac;
}

/**
 * @returns {boolean}
 */
export function isMobileOS() {
    return isAndroid() || isIOS() || isOtherMobileOS();
}

/**
 * @returns {boolean}
 */
export function isIosApp() {
    return _getUA().iosApp;
}

/**
 * @returns {boolean}
 */
export function isAndroidApp() {
    return _getUA().androidApp;
}

/**
 * @returns {boolean}
 */
export function isDisplayStandalone() {
    return browser.matchMedia("(display-mode: standalone)").matches;
}

/**
 * @returns {boolean}
 */
export function prefersReducedMotion() {
    return browser.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * @returns {boolean}
 */
export function hasTouch() {
    return (
        browser.ontouchstart !== undefined ||
        browser.matchMedia("(pointer:coarse)").matches
    );
}

/**
 * @returns {number}
 */
export function maxTouchPoints() {
    return browser.navigator.maxTouchPoints || 0;
}

/**
 * @returns {boolean}
 */
export function isVirtualKeyboardSupported() {
    return "virtualKeyboard" in browser.navigator;
}
