// @ts-check
/** @odoo-module native */

/** @module @web/services/slow_rpc_service - Sticky toast when an RPC exceeds the patience threshold; auto-dismissed on response */

import { browser } from "@web/core/browser/browser";
import { RpcEvent } from "@web/core/events";
import { _t } from "@web/core/l10n/translation";
import { rpcBus } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";

/**
 * Patience threshold in ms — 5 s is the usual "user wonders if it's broken"
 * cliff. Exposed as a mutable object so deployment-time tuning (future:
 * read `slow_rpc.threshold_ms` via session_info) and tests can override it.
 */
export const SLOW_RPC_CONFIG = { thresholdMs: 5000 };

/**
 * Shows a single shared toast while at least one non-silent RPC exceeds
 * {@link SLOW_RPC_CONFIG}.thresholdMs; clears it once every slow request got
 * its `RPC:RESPONSE` (success, error, abort, or timeout). Silent RPCs
 * (boot-time metadata, action loads, retries) opt out, same as they do for
 * error dialogs.
 */
export const slowRpcService = {
    dependencies: ["notification"],
    /**
     * @param {import("@web/env").OdooEnv} _env
     * @param {{ notification: { add: (msg: string, opts?: any) => () => void } }} services
     */
    start(_env, { notification }) {
        /** @type {Map<number, { timeoutId: any, isSlow: boolean }>} */
        const pending = new Map();
        // One shared toast, refcounted: N concurrent slow RPCs must not stack
        // N identical notifications. Shown on the first threshold crossing,
        // closed when the last slow request settles.
        let slowCount = 0;
        /** @type {(() => void) | null} */
        let closeNotification = null;

        rpcBus.addEventListener(RpcEvent.REQUEST, (event) => {
            const detail = /** @type {any} */ (event).detail;
            if (!detail?.data) {
                return;
            }
            const { data, settings } = detail;
            // Same silent opt-out as the loading indicator (the only other
            // RPC:REQUEST consumer that honors it). Note ``silent`` does NOT
            // suppress error dialogs — the error service ignores it.
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
            pending.delete(rpcId);
            if (entry.isSlow) {
                slowCount--;
                if (slowCount === 0) {
                    closeNotification?.();
                    closeNotification = null;
                }
            }
        });
    },
};

registry.category("services").add("slow_rpc", slowRpcService);
