/** @odoo-module native */
import { cookie } from "@web/core/browser/cookie";
import { makeLogger } from "@web/core/debug/debug_logger";
import { patch } from "@web/core/utils/patch";

const log = makeLogger("website.utils.http_cookie");

patch(cookie, {
    isAllowedCookie(type) {
        if (type === "optional") {
            if (!document.getElementById("cookies-consent-essential")) {
                log.logic("isAllowedCookie: no cookies bar, optional allowed");
                return true;
            }
            let consents;
            try {
                consents = JSON.parse(cookie.get("website_cookies_bar") || "{}");
            } catch {
                log.logic("isAllowedCookie: unparsable consent cookie");
                consents = null;
            }

            if (typeof consents !== "object" || consents === null) {
                log.logic(
                    "isAllowedCookie: invalid consents, cookie deleted, optional refused",
                );
                cookie.delete("website_cookies_bar");
                return false;
            }

            log.logic("isAllowedCookie: consent decision", () => ({
                hasOptional: "optional" in consents,
                optional: consents["optional"],
            }));
            if ("optional" in consents) {
                return consents["optional"];
            }
            return false;
        }
        return true;
    },
    set(key, value, ttl, type = "required") {
        log.logic("set", () => ({ key, type, ttl }));
        super.set(key, value, this.isAllowedCookie(type) ? ttl : 0);
    },
});
