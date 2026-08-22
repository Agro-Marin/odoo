// @ts-check
/** @odoo-module native */

import { LruCache } from "@web/core/utils/lru_cache";

const DEFAULT_LIMIT = 512;

export class SpecialDataCache extends LruCache {
    /** @param {number} [limit] */
    constructor(limit = DEFAULT_LIMIT) {
        super(limit);
    }
}
