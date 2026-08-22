/** @odoo-module native */
import { toRaw } from "@odoo/owl";
import { WithLazyGetterTrap } from "@point_of_sale/lazy_getter";
import { luxon } from "@web/core/l10n/luxon";

import { clone, deepImmutable, RAW_SYMBOL } from "./utils.js";
const { DateTime } = luxon;

export class Base extends WithLazyGetterTrap {
    static excludedLazyGetters = ["id", "models"];

    constructor({ model, raw }) {
        super({});
        this.model = model;
        this[RAW_SYMBOL] = raw;
    }

    get models() {
        return this.model.models;
    }

    get id() {
        return this[RAW_SYMBOL].id;
    }

    get isSynced() {
        return typeof this.id === "number";
    }

    get raw() {
        return deepImmutable(clone(this[RAW_SYMBOL]), "Raw data cannot be modified");
    }

    /**
     * @param {*} _vals
     */
    setup(vals) {
        this._dirty = vals?.__dirty ?? !this.isSynced;
        this._dirtyFields = new Set();
    }

    initState() {}

    restoreState(uiState) {
        this.uiState = uiState;
    }

    isDirty() {
        return this._dirty;
    }

    formatDateOrTime(field, type = "datetime") {
        let value = this[field];
        if (typeof value === "string") {
            value = DateTime.fromISO(value);
        }
        if (!value) {
            return "";
        }
        if (type === "date") {
            return value.toLocaleString(DateTime.DATE_SHORT);
        }
        return value.toLocaleString(DateTime.DATETIME_SHORT);
    }

    isEqual(other) {
        return toRaw(this) === toRaw(other);
    }

    update(vals, opts = {}) {
        return this.model.update(this, vals, opts);
    }

    delete(opts = {}) {
        return this.model.delete(this, opts);
    }

    serializeForORM(opts = {}) {
        return this.model.serializeForORM(this, opts);
    }

    serializeForIndexedDB() {
        return this.model.serializeForIndexedDB(this);
    }

    serializeState() {
        if (!this.uiState) {
            return;
        }
        return { ...this.uiState };
    }

    backLink(link) {
        return this.model.backLink(this, link);
    }

    _markDirty(fields = null) {
        if (this.models._loadingData) {
            return;
        }

        if (fields?.length) {
            this._dirtyFields ??= new Set();
            for (const field of fields) {
                this._dirtyFields.add(field);
            }
        }

        const visited = new Set();
        const walk = (rec) => {
            const raw = toRaw(rec);
            if (visited.has(raw)) {
                return;
            }
            visited.add(raw);
            rec._dirtyEpoch = (rec._dirtyEpoch ?? 0) + 1;
            rec._dirty = true;
            rec.model.getParentFields().forEach((field) => {
                const parent = rec[field.name];
                if (parent?._markDirty) {
                    walk(parent);
                }
            });
        };
        walk(this);
    }

    _markClean() {
        this._dirty = false;
        this._dirtyFields = new Set();
    }
}
