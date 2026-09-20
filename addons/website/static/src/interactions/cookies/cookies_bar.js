/** @odoo-module native */
import { cookie } from "@web/core/browser/cookie";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { isVisible } from "@web/core/utils/dom/ui";
import { Popup } from "@website/interactions/popup/popup";
import { cloneContentEls } from "@website/js/utils";
import { setUtmsHtmlDataset } from "@website/utils/misc";

const log = makeLogger("website.interaction.cookies_bar");

export class CookiesBar extends Popup {
    static selector = "#website_cookies_bar";
    dynamicSelectors = {
        ...this.dynamicSelectors,
        _cookiesbus: () => this.services.website_cookies.bus,
    };
    dynamicContent = {
        ...this.dynamicContent,
        _cookiesbus: {
            "t-on-cookiesBar.show": this.onShowCookiesBar,
            "t-on-cookiesBar.toggle": this.onToggleCookiesBar,
        },
        "#cookies-consent-essential, #cookies-consent-all": {
            "t-on-click": this.onAcceptClick,
        },
        ".js_close_popup": { "t-on-click": () => {} },
        ".btn-primary": { "t-on-click": () => {} },
        ".modal": {
            "t-on-keydown.capture": (ev) => {
                if (ev.key === "Escape") {
                    ev.stopImmediatePropagation();
                }
            },
        },
    };

    setup() {
        super.setup();
        this.showToggle();
        log.lifecycle("CookiesBar setup", () => ({
            popupAlreadyShown: this.popupAlreadyShown,
            hasToggle: !!this.toggleEl,
        }));
    }

    start() {
        super.start();

        const copyrightFooterContainerEl = document.querySelector(
            ".o_footer_copyright_name",
        )?.parentElement;
        if (copyrightFooterContainerEl) {
            const cookiePolicyLinkEl = cloneContentEls(`
                <p><a href="/cookie-policy" class="o_cookie_policy_link">${_t(
                    "Cookie Policy",
                )}</a></p>
            `).firstElementChild;
            log.logic("CookiesBar start: insert footer cookie policy link", () => ({
                container: copyrightFooterContainerEl.className,
            }));
            this.insert(cookiePolicyLinkEl, copyrightFooterContainerEl);
        }

        const originalTrackingCodeScriptEl = document.querySelector(
            "#tracking_code_config",
        );
        if (originalTrackingCodeScriptEl) {
            document.removeEventListener(
                "optionalCookiesAccepted",
                window.allConsentsGranted,
            );

            const updatedTrackingCodeScript = `
                window.dataLayer = window.dataLayer || [];
                function gtag() {
                    dataLayer.push(arguments);
                }

                function updateConsents(consentState) {
                    gtag("consent", "update", {
                        "ad_storage": consentState,
                        "ad_user_data": consentState,
                        "ad_personalization": consentState,
                        "analytics_storage": consentState,
                    });
                }

                document.addEventListener("optionalCookiesAccepted", () => {
                    updateConsents("granted");
                });

                document.addEventListener("optionalCookiesDenied", () => {
                    updateConsents("denied");
                });
            `;
            const newScriptEl = document.createElement("script");
            newScriptEl.id = "tracking_code_config";
            newScriptEl.textContent = updatedTrackingCodeScript;

            originalTrackingCodeScriptEl.parentNode.replaceChild(
                newScriptEl,
                originalTrackingCodeScriptEl,
            );
            log.logic(
                "CookiesBar start: tracking code consent script replaced",
                () => ({
                    hadAllConsentsGranted: !!window.allConsentsGranted,
                }),
            );
        }
    }

    showPopup() {
        super.showPopup();
        if (this.toggleEl) {
            log.logic("CookiesBar showPopup: toggle present, toggle bar", () => ({
                popupAlreadyShown: this.popupAlreadyShown,
            }));
            this.onToggleCookiesBar();
        }
    }

    showToggle() {
        const policyLinkEl = this.el.querySelector(".o_cookies_bar_text_policy");
        if (
            policyLinkEl &&
            window.location.pathname === new URL(policyLinkEl.href).pathname
        ) {
            this.toggleEl = cloneContentEls(`
            <button class="o_cookies_bar_toggle btn btn-info btn-sm rounded-circle d-flex gap-2 align-items-center position-fixed pe-auto">
                <i class="fa-regular fa-eye" alt="" aria-hidden="true"></i> <span class="o_cookies_bar_toggle_label"></span>
            </button>
            `).firstElementChild;
            log.logic("CookiesBar showToggle: on policy page, insert toggle", () => ({
                pathname: window.location.pathname,
            }));
            this.insert(this.toggleEl, this.el, "beforebegin");
        }
    }

    onToggleCookiesBar() {
        this.cookieValue = cookie.get(this.el.id);
        log.logic("CookiesBar onToggleCookiesBar", () => ({
            hasCookie: !!this.cookieValue,
            shown: this.modalEl.classList.contains("show"),
        }));
        this.bsModal.toggle();
        this.popupAlreadyShown = false;
    }

    /**
     * @param {MouseEvent} ev
     */
    onAcceptClick(ev) {
        const isFullConsent = ev.currentTarget.id === "cookies-consent-all";
        this.cookieValue = `{"required": true, "optional": ${isFullConsent}, "ts": ${Date.now()}}`;
        log.logic("CookiesBar onAcceptClick: consent", () => ({
            isFullConsent,
            button: ev.currentTarget.id,
        }));
        if (isFullConsent) {
            document.dispatchEvent(new Event("optionalCookiesAccepted"));
        } else {
            document.dispatchEvent(new Event("optionalCookiesDenied"));
        }
        this.bsModal.hide();
        this.services.website_cookies.bus.trigger("cookiesBar.discard");
    }

    onHideModal() {
        super.onHideModal();
        const params = new URLSearchParams(window.location.search);
        const trackingFields = {
            utm_campaign: "odoo_utm_campaign",
            utm_source: "odoo_utm_source",
            utm_medium: "odoo_utm_medium",
        };
        for (const [key, value] of params) {
            if (key in trackingFields) {
                cookie.set(trackingFields[key], value, 31 * 24 * 60 * 60, "optional");
            }
        }
        log.pipeline("CookiesBar onHideModal: utm cookies set", () => ({
            utms: [...params.keys()].filter((key) => key in trackingFields),
        }));
        setUtmsHtmlDataset();
    }

    onShowCookiesBar() {
        const currCookie = cookie.get(this.el.id);
        let optionalAccepted;
        try {
            optionalAccepted = !!(currCookie && JSON.parse(currCookie).optional);
        } catch {
            optionalAccepted = false;
        }
        if (optionalAccepted || !this.popupAlreadyShown) {
            log.logic("CookiesBar onShowCookiesBar: skipped", () => ({
                optionalAccepted,
                popupAlreadyShown: this.popupAlreadyShown,
            }));
            return;
        }
        this.bsModal.show();

        if (!isVisible(this.modalEl)) {
            log.logic("CookiesBar onShowCookiesBar: bar blocked, not visible", () => ({
                id: this.el.id,
            }));
            window.alert(
                _t("Our cookies bar was blocked by your browser or an extension."),
            );
            return;
        }
        this.modalEl.focus();
    }
}

registry.category("public.interactions").add("website.cookies_bar", CookiesBar);
