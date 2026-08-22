// @ts-check
/** @odoo-module native */

/** @type {number} */
const COOKIE_TTL = 24 * 60 * 60 * 365;

// eslint-disable-next-line no-control-regex
const UNSAFE_VALUE_CHARS = /[%;\x00-\x1f\x7f]/g;
// eslint-disable-next-line no-control-regex
const UNSAFE_KEY_CHARS = /[%;=,\s()<>@:\\"/[\]?{}\x00-\x1f\x7f]/g;

/**
 * @param {string} str
 * @returns {string}
 */
function escapeCookieComponent(str, pattern = UNSAFE_VALUE_CHARS) {
    return String(str).replace(pattern, (c) => encodeURIComponent(c));
}

/**
 * @param {string | undefined} str
 * @returns {string}
 */
function decodeCookieComponent(str) {
    try {
        return decodeURIComponent(str ?? "");
    } catch {
        return str ?? "";
    }
}

export const cookie = {
    /** @returns {string} */
    get _cookieMonster() {
        return document.cookie;
    },
    /** @param {string} value */
    set _cookieMonster(value) {
        document.cookie = value;
    },
    /**
     * @param {string} str
     * @returns {string | undefined}
     */
    get(str) {
        const parts = this._cookieMonster.split("; ");
        for (const part of parts) {
            const [rawKey, value] = part.split(/=(.*)/);
            const key = decodeCookieComponent(rawKey);
            if (key === str) {
                if (!value) {
                    return "";
                }
                return decodeCookieComponent(value);
            }
        }
    },
    /**
     * @param {string} key
     * @param {string | undefined} value
     * @param {number} [ttl]
     */
    set(key, value, ttl = COOKIE_TTL) {
        if (value === undefined) {
            this.delete(key);
            return;
        }
        const parts = [
            `${escapeCookieComponent(key, UNSAFE_KEY_CHARS)}=${escapeCookieComponent(value)}`,
            "path=/",
            `max-age=${Math.floor(ttl)}`,
            "SameSite=Lax",
        ];
        this._cookieMonster = parts.join("; ");
    },
    /** @param {string} key */
    delete(key) {
        this.set(key, "", 0);
    },
};
