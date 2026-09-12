// @ts-check
/** @odoo-module native */
import { reactive } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";

import { logPosMessage } from "../utils/pretty_console_log.js";
const log = makeLogger("pos.stock");

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
        let added = 0;
        for (const id of productIds) {
            if (!(id in this.quantities) && !this.pending.has(id)) {
                this.pending.add(id);
                added++;
            }
        }
        log.logic("request", () => ({
            added,
            pending: this.pending.size,
            schedule: this.pending.size > 0 && !this.flushScheduled,
        }));
        if (this.pending.size && !this.flushScheduled) {
            this.flushScheduled = true;
            Promise.resolve().then(() => this.flush());
        }
    }

    refresh() {
        const known = Object.keys(this.quantities).map(Number);
        log.pipeline("refresh", () => ({ known: known.length }));
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
        const endFlush = log.perf("flush get_pos_stock_quantities");
        try {
            const result = await this.orm.call(
                "product.product",
                "get_pos_stock_quantities",
                [ids, this.pos.config.id],
            );
            for (const id of ids) {
                this.quantities[id] = result[id] ?? 0;
            }
            endFlush({ products: ids.length });
        } catch (error) {
            for (const id of ids) {
                this.quantities[id] = null;
            }
            endFlush({ products: ids.length, failed: true });
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
