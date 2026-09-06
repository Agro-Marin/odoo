// @ts-check
/** @odoo-module native */
import { reactive } from "@odoo/owl";
import { registry } from "@web/core/registry";

import { logPosMessage } from "../utils/pretty_console_log.js";

/**
 * On-hand quantities for the product cards, keyed by product.product id.
 *
 * Requests issued in one tick travel as one call, a quantity is fetched once
 * per session, and `refresh()` refetches every product the session knows.
 * `null` marks a product whose fetch failed, `undefined` one still pending.
 */
export class PosStockService {
    /**
     * @param {object} env
     * @param {{ orm: any, pos: any }} deps
     */
    constructor(env, { orm, pos }) {
        this.orm = orm;
        this.pos = pos;
        /** @type {Record<number, number | null>} */
        this.quantities = reactive({});
        /** @type {Set<number>} */
        this.pending = new Set();
        this.flushScheduled = false;
    }

    /**
     * @param {Iterable<number>} productIds
     */
    request(productIds) {
        for (const id of productIds) {
            if (!(id in this.quantities) && !this.pending.has(id)) {
                this.pending.add(id);
            }
        }
        if (this.pending.size && !this.flushScheduled) {
            this.flushScheduled = true;
            Promise.resolve().then(() => this.flush());
        }
    }

    refresh() {
        const known = Object.keys(this.quantities).map(Number);
        for (const id of known) {
            delete this.quantities[id];
        }
        this.request(known);
    }

    async flush() {
        this.flushScheduled = false;
        const ids = [...this.pending];
        this.pending.clear();
        if (!ids.length) {
            return;
        }
        try {
            const result = await this.orm.call(
                "product.product",
                "get_pos_stock_quantities",
                [ids, this.pos.config.id],
            );
            for (const id of ids) {
                this.quantities[id] = result[id] ?? 0;
            }
        } catch (error) {
            for (const id of ids) {
                this.quantities[id] = null;
            }
            logPosMessage(
                "PosStockService",
                "flush",
                "Quantity fetch failed",
                undefined,
                [error],
            );
        }
    }
}

export const posStockService = {
    dependencies: ["orm", "pos"],
    /**
     * @param {object} env
     * @param {{ orm: any, pos: any }} deps
     */
    start(env, { orm, pos }) {
        return new PosStockService(env, { orm, pos });
    },
};

registry.category("services").add("pos_stock", posStockService);
