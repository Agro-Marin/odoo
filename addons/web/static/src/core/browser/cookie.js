// @ts-check
/** @odoo-module native */

/** @module @web/core/browser/cookie - Read, write, and delete browser cookies via document.cookie */

/**
 * Utils to make use of document.cookie
 * https://developer.mozilla.org/en-US/docs/Web/HTTP/Cookies
 * As recommended, storage should not be done by the cookie
 * but with localStorage/sessionStorage
 */

/** @type {number} Default cookie time-to-live in seconds (1 year). */
const COOKIE_TTL = 24 * 60 * 60 * 365;

export const cookie = {
    /** @returns {string} The raw document.cookie string. */
    get _cookieMonster() {
        return document.cookie;
    },
    /** @param {string} value - Raw cookie string to assign to document.cookie. */
    set _cookieMonster(value) {
        document.cookie = value;
    },
    /**
     * @param {string} str - Cookie name to look up.
     * @returns {string | undefined} The cookie value, or undefined if not found.
     */
    get(str) {
        const parts = this._cookieMonster.split("; ");
        for (const part of parts) {
            const [key, value] = part.split(/=(.*)/);
            if (key === str) {
                if (!value) {
                    return "";
                }
                // Reverse the write-side escaping (see `set`). Legacy/raw
                // values containing a bare `%` would make decodeURIComponent
                // throw — return them untouched instead.
                try {
                    return decodeURIComponent(value);
                } catch {
                    return value;
                }
            }
        }
    },
    /**
     * @param {string} key - Cookie name.
     * @param {string | undefined} value - Cookie value. Passing `undefined`
     *  deletes the cookie (see below).
     * @param {number} [ttl] - Time-to-live in seconds (defaults to 1 year).
     */
    set(key, value, ttl = COOKIE_TTL) {
        if (value === undefined) {
            // A name-only assignment (`document.cookie = "key; path=/…"`) is
            // parsed by browsers as an *empty-named* cookie whose value is
            // "key" — never a cookie named `key`. That trap is never what a
            // caller wants, so treat a missing value as a deletion instead.
            this.delete(key);
            return;
        }
        // Escape ONLY the characters that corrupt the cookie string: `;`
        // truncates the value, a bare `%` breaks the read-side decoding, and
        // control characters make the whole `document.cookie` assignment a
        // silent no-op. Deliberately NOT a full encodeURIComponent: several
        // cookies are a cross-layer protocol whose raw value the server
        // parses as-is — e.g. the `website_cookies_bar` consent JSON
        // (`ir_http._is_allowed_cookie` json-loads it, spaces/commas/quotes
        // included), `frontend_lang`, `cids` — so anything the browser
        // tolerates must be written through unchanged.
        const encoded = String(value).replace(
            // eslint-disable-next-line no-control-regex
            /[%;\x00-\x1f\x7f]/g,
            (c) => encodeURIComponent(c),
        );
        const parts = [
            `${key}=${encoded}`,
            "path=/",
            `max-age=${Math.floor(ttl)}`,
            // All uses are first-party; Lax matches the modern browser
            // default but makes it explicit (and consistent) everywhere.
            "SameSite=Lax",
        ];
        this._cookieMonster = parts.join("; ");
    },
    /** @param {string} key - Cookie name to remove. */
    delete(key) {
        this.set(key, "", 0);
    },
};
