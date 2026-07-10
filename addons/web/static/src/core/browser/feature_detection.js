// @ts-check
/** @odoo-module native */

/** @module @web/core/browser/feature_detection - Browser and device capability checks (Chrome, mobile, touch, PWA) */

import { browser } from "./browser.js";

// UA-based detection cache
//
// UA-based checks are pure functions of a single immutable input (navigator.userAgent).
// Results are computed once per unique UA string and cached; the cache only
// invalidates in tests that patch browser.navigator to a different UA.

/** @type {string | undefined} */
let _cachedUA;

/** @type {ReturnType<typeof _computeUAResults> | undefined} */
let _uaResults;

/**
 * Compute all UA-based detection results from a single pass.
 *
 * @param {string} ua - navigator.userAgent value
 */
function _computeUAResults(ua) {
    const chrome = /Chrome/i.test(ua);
    return {
        chrome,
        firefox: /Firefox/i.test(ua),
        edge: /Edg/i.test(ua),
        safari: !chrome && ua.includes("Safari"),
        android: /Android/i.test(ua),
        iosUA: /(iPad|iPhone|iPod)/i.test(ua),
        otherMobile: /(webOS|BlackBerry|Windows Phone)/i.test(ua),
        mac: /Mac/i.test(ua),
        iosApp: /OdooMobile \(iOS\)/i.test(ua),
        androidApp: /OdooMobile.+Android/i.test(ua),
    };
}

/**
 * Return the cached UA results, recomputing if the user agent has changed.
 * In production this computes once; in tests it recomputes when browser.navigator
 * is patched to a different UA string.
 */
function _getUA() {
    const ua = browser.navigator.userAgent || "";
    if (ua !== _cachedUA) {
        _cachedUA = ua;
        _uaResults = _computeUAResults(ua);
    }
    return /** @type {NonNullable<typeof _uaResults>} */ (_uaResults);
}

// Feature detection

/**
 * True if the browser is based on Chromium (Google Chrome, Opera, Edge).
 *
 * @returns {boolean}
 */
export function isBrowserChrome() {
    return _getUA().chrome;
}

/**
 * True if the browser is Firefox.
 *
 * @returns {boolean}
 */
export function isBrowserFirefox() {
    return _getUA().firefox;
}

/**
 * True if the browser is Microsoft Edge.
 *
 * @returns {boolean}
 */
export function isBrowserMicrosoftEdge() {
    return _getUA().edge;
}

/**
 * True if the browser is based on Safari (Safari, Epiphany).
 *
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
    // iPad Safari reports as "MacIntel" — detect via touch capability
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
