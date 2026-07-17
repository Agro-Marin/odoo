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
     * Called during instantiation when the instance is fully-populated with field values.
     * This method is called when the instance is created or updated
     * @param {*} _vals
     */
    setup(vals) {
        // __dirty is the persisted dirty marker written by
        // serializeForIndexedDB: without it, offline edits to a synced record
        // come back "clean" after a reload and are never synced.
        this._dirty = vals?.__dirty ?? !this.isSynced;
        // A (re)setup starts a fresh divergence-tracking window; a restored
        // dirty record re-serializes in full anyway.
        this._dirtyFields = new Set();
    }

    /**
     *  This method is invoked only during instance creation to preserve the state across updates.
     */
    initState() {}

    /**
     *  Restore state serialized from indexedDB
     */
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

        // Track WHICH fields diverged since the last clean state: the
        // sync-response processing needs them to re-apply edits made while
        // the RPC was in flight (the server echo reflects the serialized,
        // pre-edit state). Only the record itself accumulates field names —
        // parents are merely marked dirty.
        if (fields?.length) {
            this._dirtyFields ??= new Set();
            for (const field of fields) {
                this._dirtyFields.add(field);
            }
        }

        // The epoch is bumped on EVERY dirtying write, even when the record is
        // already dirty: a deferred serialization clear (serializeForORM with
        // deferClear) only marks a record clean when its epoch is unchanged
        // since serialize time, so edits made while a sync RPC is in flight
        // survive the commit instead of being silently consumed. The bump is
        // propagated to parents for the same reason (the visited set guards
        // against relation cycles).
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
