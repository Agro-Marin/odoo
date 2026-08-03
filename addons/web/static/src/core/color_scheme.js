// @ts-check
/** @odoo-module native */

/** @module @web/core/color_scheme */

import { reactive, useState } from "@odoo/owl";
import { cookie } from "@web/core/browser/cookie";

const COOKIE = "color_scheme";

/**
 * Bumped by every publication.
 *
 * The number means nothing; reading it is how a component subscribes. The
 * scheme itself is deliberately *not* kept here: `current` stays a live read of
 * the cookie, so there is one source of truth and nothing beside it to go
 * stale.
 */
const revision = reactive({ count: 0 });

/**
 * Reading the revision is what registers the caller's render.
 *
 * @param {typeof revision} tracked
 */
function subscribe(tracked) {
    return tracked.count;
}

/**
 * The colour scheme in effect, resolved to light or dark.
 *
 * The cookie behind this is a transport detail: it is how the server hands the
 * answer over at boot, and `webclient_bootstrap` settles it inline before any
 * bundle runs. Read it through here rather than directly, so the storage stays
 * an implementation detail and there is one place that knows what an absent or
 * unexpected value means.
 *
 * Publication lives here too, beside the read. The cookie and the
 * `data-color-scheme` attribute say the same thing — one is what JS reads, the
 * other what the token layer answers — and every way of arriving at a scheme
 * has to leave both saying it. With the writer in `webclient/` and the reader
 * in `core/`, two modules knew the cookie's name, its value set and its
 * companion attribute; now one does, and `test_color_scheme_reads` has one
 * file to exempt instead of two.
 *
 * Getters, not values, on purpose: whether the scheme can change without
 * re-serving the page is not something a caller should encode.
 */
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
     * Publish *scheme* as the settled answer, in both places that carry it.
     *
     * @param {"light" | "dark"} scheme
     */
    publish(scheme) {
        cookie.set(COOKIE, scheme);
        document.documentElement.dataset.colorScheme = scheme;
        revision.count++;
    },
};

/**
 * The same reading, subscribed: the calling component re-renders when the
 * scheme is republished.
 *
 * A `system` user is served both stylesheets behind `prefers-color-scheme`, so
 * the OS switching theme repaints the page without asking anyone — and a
 * component that read the scheme once at setup keeps drawing the other one.
 * The dark-mode toggle offering a sun over a dark page is the visible case.
 *
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
