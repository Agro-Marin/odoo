// @ts-check
/** @odoo-module native */

import { LruCache } from "@web/core/utils/lru_cache";

const BREADCRUMB_CACHE_LIMIT = 200;

export class BreadcrumbCache extends LruCache {
    /** @param {number} [limit] */
    constructor(limit = BREADCRUMB_CACHE_LIMIT) {
        super(limit);
    }
}
