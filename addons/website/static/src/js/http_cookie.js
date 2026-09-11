/** @odoo-module native */
import { cookie } from "@web/core/browser/cookie";
import { patch } from "@web/core/utils/patch";

patch(cookie, {
    isAllowedCookie(type) {
        if (type === "optional") {
            if (!document.getElementById("cookies-consent-essential")) {
                return true;
            }
            let consents;
            try {
                consents = JSON.parse(cookie.get("website_cookies_bar") || "{}");
            } catch {
                consents = null;
            }

            if (typeof consents !== "object" || consents === null) {
                cookie.delete("website_cookies_bar");
                return false;
            }

            if ("optional" in consents) {
                return consents["optional"];
            }
            return false;
        }
        return true;
    },
    set(key, value, ttl, type = "required") {
        super.set(key, value, this.isAllowedCookie(type) ? ttl : 0);
    },
});
