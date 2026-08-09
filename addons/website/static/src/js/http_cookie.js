/** @odoo-module native */
import { cookie } from "@web/core/browser/cookie";
import { patch } from "@web/core/utils/patch";

patch(cookie, {
    isAllowedCookie(type) {
        if (type === "optional") {
            if (!document.getElementById("cookies-consent-essential")) {
                // Cookies bar is disabled on this website.
                return true;
            }
            let consents;
            try {
                consents = JSON.parse(cookie.get("website_cookies_bar") || "{}");
            } catch {
                // The value is client-side state: it can be truncated, mangled
                // by another app on the domain, or forged. The pre-16.0 branch
                // below only catches values that still *parse* (`"true"` parses
                // to a boolean); an unparseable one threw out of here and out of
                // every `cookie.set()` that consults this gate. Same treatment
                // either way -- and the same as the server's
                // `ir.http._is_allowed_cookie`: drop it and ask again.
                consents = null;
            }

            // pre-16.0 compatibility, `website_cookies_bar` was `"true"`.
            // In that case we delete that cookie and let the user choose again.
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
