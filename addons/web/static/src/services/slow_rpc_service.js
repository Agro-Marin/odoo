// @ts-check
/** @odoo-module native */

/** @module @web/services/slow_rpc_service - Sticky toast when an RPC exceeds the patience threshold; auto-dismissed on response */

import { browser } from "@web/core/browser/browser";
import { RpcEvent } from "@web/core/events";
import { _t } from "@web/core/l10n/translation";
import { rpcBus } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";

/**
 * Patience threshold in milliseconds. 5 s is the cliff most usability
 * research uses as the "user starts to wonder if it's broken" mark.
 *
 * Exposed as a mutable config object so deployment-time tuning can land
 * without an API change (next step: read from `slow_rpc.threshold_ms`
 * ir.config_parameter via `session_info`), and so tests can lower it
 * to fire on a 1 ms `advanceTime`.
 */
export const SLOW_RPC_CONFIG = { thresholdMs: 5000 };

/**
 * Listens passively on `rpcBus` and shows a toast notification when
 * any non-silent RPC exceeds {@link SLOW_RPC_CONFIG}.thresholdMs.
 * Disposes the toast as soon as the matching `RPC:RESPONSE` event
 * arrives — success, error, abort, and timeout responses all clear
 * the timer.
 *
 * Pairs with the existing `silent` setting: silent RPCs (boot-time
 * field metadata, action loads, retry-internal calls) opt out of the
 * patience UI just as they opt out of error dialogs.
 */
export const slowRpcService = {
    dependencies: ["notification"],
    /**
     * @param {import("@web/env").OdooEnv} _env
     * @param {{ notification: { add: (msg: string, opts?: any) => () => void } }} services
     */
    start(_env, { notification }) {
        /** @type {Map<number, { timeoutId: any, closeNotification?: () => void }>} */
        const pending = new Map();

        rpcBus.addEventListener(RpcEvent.REQUEST, (event) => {
            const detail = /** @type {any} */ (event).detail;
            if (!detail?.data) {
                return;
            }
            const { data, settings } = detail;
            // ``silent`` requests already opt out of error dialogs;
            // patience UI follows the same rule for consistency.
            if (settings?.silent) {
                return;
            }
            const rpcId = data.id;
            /** @type {{ timeoutId: number, closeNotification?: () => void }} */
            const entry = { timeoutId: 0 };
            pending.set(rpcId, entry);
            entry.timeoutId = browser.setTimeout(() => {
                entry.closeNotification = notification.add(
                    _t("This is taking longer than usual…"),
                    { type: "info", sticky: true },
                );
            }, SLOW_RPC_CONFIG.thresholdMs);
        });

        rpcBus.addEventListener(RpcEvent.RESPONSE, (event) => {
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
            entry.closeNotification?.();
            pending.delete(rpcId);
        });
    },
};

registry.category("services").add("slow_rpc", slowRpcService);
