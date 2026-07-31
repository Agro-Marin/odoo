// @ts-check
/** @odoo-module native */

/** @module @web/core/browser/cookie */

/** @type {number} */
const COOKIE_TTL = 24 * 60 * 60 * 365;

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
            const [key, value] = part.split(/=(.*)/);
            if (key === str) {
                if (!value) {
                    return "";
                }
                try {
                    return decodeURIComponent(value);
                } catch {
                    return value;
                }
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
        const encoded = String(value).replace(
            // eslint-disable-next-line no-control-regex
            /[%;\x00-\x1f\x7f]/g,
            (c) => encodeURIComponent(c),
        );
        const parts = [
            `${key}=${encoded}`,
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
