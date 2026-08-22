// @ts-check
/** @odoo-module native */

import { browser } from "@web/core/browser/browser";
import { router } from "@web/core/browser/router";
import { _t } from "@web/core/translation";

export const UNIT_TESTS_URL = "/web/tests?debug=assets";

/** @returns {string} */
export const unitTestsLabel = () => _t("Run Unit Tests");

export function openUnitTests() {
    browser.open(UNIT_TESTS_URL);
}

/**
 * @param {string|number} debug
 */
function setDebug(debug) {
    router.pushState({ debug }, { reload: true });
}

export function leaveDebugMode() {
    setDebug(0);
}

export function enterDebugMode() {
    setDebug("1");
}

export function enterDebugModeWithAssets() {
    setDebug("assets");
}

export function enterTestMode() {
    setDebug("assets,tests");
}
