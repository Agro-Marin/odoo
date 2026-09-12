// @ts-check
/** @odoo-module native */
import { reactive } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import {
    isAndroidApp,
    isDisplayStandalone,
    isIOS,
    isIosApp,
} from "@web/core/browser/feature_detection";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";

const log = makeLogger("mail.notification_permission");
/** @returns {Promise<PermissionState>} */
async function getIosPwaPermission() {
    if (browser.location.protocol !== "https:") {
        return "denied";
    }
    const registration = await browser.navigator.serviceWorker?.getRegistration();
    return (await registration?.pushManager.permissionState()) ?? "prompt";
}

export const notificationPermissionService = {
    dependencies: ["notification"],

    /**
     * @param {NotificationPermission|PermissionState|undefined} permission
     * @returns {"prompt"|"granted"|"denied"}
     */
    _normalizePermission(permission) {
        switch (permission) {
            case "default":
                return "prompt";
            case undefined:
                return "denied";
            default:
                return permission;
        }
    },

    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {import("services").ServiceFactories} services
     */
    async start(env, services) {
        const notification = services.notification;
        /** @type {PermissionStatus | {state: PermissionState} | undefined} */
        let permission;
        try {
            if (isIOS() && isDisplayStandalone()) {
                permission = { state: await getIosPwaPermission() };
            } else if (isIOS()) {
                permission = { state: "denied" };
            } else {
                permission = await browser.navigator?.permissions?.query({
                    name: "notifications",
                });
            }
        } catch {}
        log.lifecycle("start", () => ({
            queried: permission?.state,
            browser: browser.Notification?.permission,
            ios: isIOS(),
            standalone: isDisplayStandalone(),
        }));
        const state = reactive({
            /** @type {"prompt" | "granted" | "denied"} */
            permission:
                isIosApp() || isAndroidApp()
                    ? "denied"
                    : this._normalizePermission(
                          permission?.state ?? browser.Notification?.permission,
                      ),
            requestPermission: async () => {
                if (browser.Notification && state.permission === "prompt") {
                    state.permission = this._normalizePermission(
                        await browser.Notification.requestPermission(),
                    );
                    log.logic("requestPermission", () => ({
                        permission: state.permission,
                    }));
                    if (state.permission === "denied") {
                        notification.add(
                            _t("Odoo will not send notifications on this device."),
                            {
                                type: "warning",
                                title: _t("Notifications blocked"),
                            },
                        );
                    } else if (state.permission === "granted") {
                        notification.add(
                            _t("Odoo will send notifications on this device!"),
                            {
                                type: "success",
                                title: _t("Notifications allowed"),
                            },
                        );
                    }
                }
            },
        });
        if (permission && "addEventListener" in permission && !isIOS()) {
            permission.addEventListener("change", () => {
                log.logic("permission change", () => ({
                    permission: permission.state,
                }));
                state.permission = permission.state;
            });
        }
        return state;
    },
};

registry
    .category("services")
    .add("mail.notification.permission", notificationPermissionService);
