/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/translation";
import { registry } from "@web/core/registry";

export const iapNotificationService = {
    dependencies: ["bus_service", "notification"],

    start(env, { bus_service, notification }) {
        bus_service.subscribe("iap_notification", (params) => {
            if (params.type == "no_credit") {
                displayCreditErrorNotification(params);
            } else {
                displayNotification(params);
            }
        });
        bus_service.start();

        function displayNotification(params) {
            notification.add(params.message, {
                title: params.title,
                type: params.type,
            });
        }

        function displayCreditErrorNotification(params) {
            // The payload carries a title and no message, so the title IS the
            // notification's text; the credits link belongs in the button area
            // rather than inline in that text.
            notification.add(params.title, {
                type: "danger",
                buttons: [
                    {
                        name: _t("Buy more credits"),
                        onClick: () => {
                            browser.open(params.get_credits_url, "_blank");
                        },
                    },
                ],
            });
        }
    },
};

registry.category("services").add("iapNotification", iapNotificationService);
