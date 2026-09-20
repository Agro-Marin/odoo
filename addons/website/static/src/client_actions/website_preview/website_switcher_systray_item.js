/** @odoo-module native */
import { Component } from "@odoo/owl";
import { Dropdown, DropdownItem } from "@web/components/dropdown";
import { browser } from "@web/core/browser/browser";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { session } from "@web/session";

import { isHTTPSorNakedDomainRedirection } from "./utils.js";

const log = makeLogger("website.systray.website_switcher");

export class WebsiteSwitcherSystrayItem extends Component {
    static template = "website.WebsiteSwitcherSystrayItem";
    static components = {
        Dropdown,
        DropdownItem,
    };
    static props = {};
    setup() {
        useLifecycleLog(log);
        this.websiteService = useService("website");
        this.notificationService = useService("notification");
        this.actionService = useService("action");
    }

    getElements() {
        return this.websiteService.websites.map((website) => ({
            name: website.name,
            id: website.id,
            domain: website.domain,
            dataset: Object.assign(
                {
                    "data-website-id": website.id,
                },
                website.domain
                    ? {}
                    : {
                          "data-tooltip": _t(
                              "This website does not have a domain configured.",
                          ),
                          "data-tooltip-position": "left",
                      },
            ),
            callback: () => {
                if (
                    !session.website_bypass_domain_redirect &&
                    website.domain &&
                    !isHTTPSorNakedDomainRedirection(
                        website.domain,
                        window.location.origin,
                    )
                ) {
                    const {
                        location: { pathname, search, hash },
                    } = this.websiteService.contentWindow;
                    const path = pathname + search + hash;
                    log.logic("switch website: redirect to other domain", () => ({
                        websiteId: website.id,
                        domain: website.domain,
                        path,
                    }));
                    const url = new URL("/web", website.domain);
                    url.hash = new URLSearchParams({
                        action: "website.website_preview",
                        path: path,
                        website_id: website.id,
                    });
                    window.location.href = url;
                } else {
                    log.logic("switch website: in-place", () => ({
                        websiteId: website.id,
                        hasDomain: Boolean(website.domain),
                        bypass: Boolean(session.website_bypass_domain_redirect),
                    }));
                    this.websiteService.goToWebsite({
                        websiteId: website.id,
                        path: "",
                        lang: "default",
                    });
                    if (!website.domain) {
                        const closeFn = this.notificationService.add(
                            _t("Add a domain to your website."),
                            {
                                type: "warning",
                                sticky: true,
                                buttons: [
                                    {
                                        onClick: () => {
                                            this.actionService.doAction(
                                                "website.action_website_configuration",
                                            );
                                            closeFn();
                                        },
                                        primary: true,
                                        name: "Settings",
                                    },
                                ],
                            },
                        );
                        browser.setTimeout(closeFn, 7000);
                    }
                }
            },
            class:
                website.id === this.websiteService.currentWebsite.id
                    ? "text-truncate active"
                    : "text-truncate",
        }));
    }
}
