/** @odoo-module native */
import { registry } from "@web/core/registry";

const NOTIFICATION_ICONS = {
    badge: "fa-certificate text-warning",
    streak: "fa-fire text-success",
    level_up: "fa-arrow-up text-primary",
    achievement: "fa-trophy text-success",
};

export const gamificationNotificationService = {
    dependencies: ["bus_service", "notification"],

    start(env, { bus_service, notification }) {
        bus_service.subscribe("gamification/notification", (payload) => {
            const icon = NOTIFICATION_ICONS[payload.type] || "fa-star";
            // Note: icon is computed above but the notification service API
            // does not support rendering a custom icon.  The type-specific
            // className (o_gamification_badge, etc.) can be styled in SCSS.
            notification.add(payload.message, {
                title: payload.title,
                type: "success",
                sticky: false,
                className: `o_gamification_notif o_gamification_${payload.type}`,
            });
        });
    },
};

registry.category("services").add("gamification_notifications", gamificationNotificationService);
