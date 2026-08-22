// @ts-check
/** @odoo-module native */

import { reactive, useState } from "@odoo/owl";
import { cookie } from "@web/core/browser/cookie";

const COOKIE = "color_scheme";

const revision = reactive({ count: 0 });

/**
 * @param {typeof revision} tracked
 */
function subscribe(tracked) {
    return tracked.count;
}

export const colorScheme = {
    /** @returns {"light" | "dark"} */
    get current() {
        return cookie.get(COOKIE) === "dark" ? "dark" : "light";
    },
    /** @returns {boolean} */
    get isDark() {
        return this.current === "dark";
    },
    /**
     * @param {"light" | "dark"} scheme
     */
    publish(scheme) {
        cookie.set(COOKIE, scheme);
        document.documentElement.dataset.colorScheme = scheme;
        revision.count++;
    },
};

/**
 * @returns {{current: "light" | "dark", isDark: boolean}}
 */
export function useColorScheme() {
    const tracked = useState(revision);
    return {
        get current() {
            subscribe(tracked);
            return colorScheme.current;
        },
        get isDark() {
            return this.current === "dark";
        },
    };
}
