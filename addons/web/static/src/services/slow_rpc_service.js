// @ts-check
/** @odoo-module native */

/** @module @web/services/slow_rpc_service */

import { browser } from "@web/core/browser/browser";
import { RpcEvent } from "@web/core/events";
import { _t } from "@web/core/l10n/translation";
import { rpcBus } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";

export const SLOW_RPC_CONFIG = { thresholdMs: 5000 };

export const slowRpcService = {
    dependencies: ["notification"],
    /**
     * @param {import("@web/env").OdooEnv} _env
     * @param {{ notification: { add: (msg: string, opts?: any) => () => void } }} services
     */
    start(_env, { notification }) {
        /** @type {Map<number, { timeoutId: any, isSlow: boolean }>} */
        const pending = new Map();
        let slowCount = 0;
        /** @type {(() => void) | null} */
        let closeNotification = null;

        const onRequest = (/** @type {any} */ event) => {
            const detail = /** @type {any} */ (event).detail;
            if (!detail?.data) {
                return;
            }
            const { data, settings } = detail;
            if (settings?.silent) {
                return;
            }
            const rpcId = data.id;
            /** @type {{ timeoutId: number, isSlow: boolean }} */
            const entry = { timeoutId: 0, isSlow: false };
            pending.set(rpcId, entry);
            entry.timeoutId = browser.setTimeout(() => {
                entry.isSlow = true;
                slowCount++;
                if (slowCount === 1) {
                    closeNotification = notification.add(
                        _t("This is taking longer than usual…"),
                        { type: "info", sticky: true },
                    );
                }
            }, SLOW_RPC_CONFIG.thresholdMs);
        };

        const onResponse = (/** @type {any} */ event) => {
            const detail = /** @type {any} */ (event).detail;
            const rpcId = detail?.data?.id;
            if (rpcId === undefined) {
                return;
            }
            const entry = pending.get(rpcId);
            if (!entry) {
                return;
            }
            browser.clearTimeout(entry.timeoutId);
            pending.delete(rpcId);
            if (entry.isSlow) {
                slowCount--;
                if (slowCount === 0) {
                    closeNotification?.();
                    closeNotification = null;
                }
            }
        };

        rpcBus.addEventListener(RpcEvent.REQUEST, onRequest);
        rpcBus.addEventListener(RpcEvent.RESPONSE, onResponse);

        return {
            destroy() {
                rpcBus.removeEventListener(RpcEvent.REQUEST, onRequest);
                rpcBus.removeEventListener(RpcEvent.RESPONSE, onResponse);
                for (const entry of pending.values()) {
                    browser.clearTimeout(entry.timeoutId);
                }
                pending.clear();
                closeNotification?.();
                closeNotification = null;
            },
        };
    },
};

registry.category("services").add("slow_rpc", slowRpcService);
