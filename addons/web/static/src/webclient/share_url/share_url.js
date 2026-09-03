// @ts-check
/** @odoo-module native */

import { markup } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import {
    isDisplayStandalone,
    isWebShareSupported,
} from "@web/core/browser/feature_detection";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";

export async function shareUrl() {
    await browser.navigator
        .share({
            url: browser.location.href,
            title: document.title,
        })
        .catch((e) => {
            if (!(e instanceof DOMException && e.name === "AbortError")) {
                throw e;
            }
        });
}

/** @param {import("@web/env").OdooEnv} env */
export function shareUrlMenuItem(env) {
    return {
        type: "item",
        hide: env.isSmall || !isDisplayStandalone(),
        id: "share_url",
        description: /** @type {any} */ (
            markup`
            <div class="d-flex align-items-center justify-content-between">
                <span>${_t("Share")}</span>
                <span class="fa-solid fa-share-alt"></span>
            </div>`
        ),
        callback: shareUrl,
        sequence: 25,
    };
}

if (isWebShareSupported()) {
    registry.category("user_menuitems").add("share_url", shareUrlMenuItem);
}
