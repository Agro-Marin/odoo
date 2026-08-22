// @ts-check
/** @odoo-module native */

import { browser } from "@web/core/browser/browser";
import { RpcEvent } from "@web/core/events";
import { rpcBus } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";

export const SLOW_RPC_CONFIG = { thresholdMs: 5000 };

class SlowRpcService {
    /**
     * @param {{ notification: { add: (msg: string, opts?: any) => () => void } }} services
     */
    constructor({ notification }) {
        this.notification = notification;
        /** @type {Map<number, { timeoutId: any, isSlow: boolean }>} */
        this.pending = new Map();
        this.slowCount = 0;
        /** @type {(() => void) | null} */
        this.closeNotification = null;

        this._onRequest = (/** @type {any} */ ev) => this.onRequest(ev);
        this._onResponse = (/** @type {any} */ ev) => this.onResponse(ev);
        rpcBus.addEventListener(RpcEvent.REQUEST, this._onRequest);
        rpcBus.addEventListener(RpcEvent.RESPONSE, this._onResponse);
    }

    /** @param {any} event */
    onRequest(event) {
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
        this.pending.set(rpcId, entry);
        entry.timeoutId = browser.setTimeout(() => {
            entry.isSlow = true;
            this.slowCount++;
            if (this.slowCount === 1) {
                this.closeNotification = this.notification.add(
                    _t("This is taking longer than usual…"),
                    { type: "info", sticky: true },
                );
            }
        }, SLOW_RPC_CONFIG.thresholdMs);
    }

    /** @param {any} event */
    onResponse(event) {
        const detail = /** @type {any} */ (event).detail;
        const rpcId = detail?.data?.id;
        if (rpcId === undefined) {
            return;
        }
        const entry = this.pending.get(rpcId);
        if (!entry) {
            return;
        }
        browser.clearTimeout(entry.timeoutId);
        this.pending.delete(rpcId);
        if (entry.isSlow) {
            this.slowCount--;
            if (this.slowCount === 0) {
                this.closeNotification?.();
                this.closeNotification = null;
            }
        }
    }

    destroy() {
        rpcBus.removeEventListener(RpcEvent.REQUEST, this._onRequest);
        rpcBus.removeEventListener(RpcEvent.RESPONSE, this._onResponse);
        for (const entry of this.pending.values()) {
            browser.clearTimeout(entry.timeoutId);
        }
        this.pending.clear();
        this.closeNotification?.();
        this.closeNotification = null;
    }
}

const slowRpcService = {
    dependencies: ["notification"],
    /**
     * @param {import("@web/env").OdooEnv} _env
     * @param {{ notification: { add: (msg: string, opts?: any) => () => void } }} services
     * @returns {SlowRpcService}
     */
    start(_env, services) {
        return new SlowRpcService(services);
    },
};

registry.category("services").add("slow_rpc", slowRpcService);
