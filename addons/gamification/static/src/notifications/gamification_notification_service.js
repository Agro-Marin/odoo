/** @odoo-module native */
import { markup } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { getNotificationIcon } from "../dashboard/gamification_dashboard_utils.js";

export const gamificationNotificationService = {
    dependencies: ["bus_service", "notification"],

    start(env, { bus_service, notification }) {
        bus_service.subscribe("gamification/notification", (payload) => {
            if (!payload?.message) {
                return;
            }
            const type = payload.type || "generic";
            // Render the type-specific glyph inline: the notification service has
            // no icon option, but its message is rendered with ``t-out`` so a
            // Markup value is honored.  The ``markup`` tagged template escapes the
            // interpolated ``message``.
            const icon = getNotificationIcon(payload.type);
            notification.add(
                markup`<i class="fa ${icon} me-2" role="img" aria-hidden="true"></i>${payload.message}`,
                {
                    title: payload.title,
                    type: "success",
                    sticky: false,
                    className: `o_gamification_notif o_gamification_${type}`,
                },
            );
        });
    },
};

registry
    .category("services")
    .add("gamification_notifications", gamificationNotificationService);
