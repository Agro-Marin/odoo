/** @odoo-module native */
import { RAW_SYMBOL } from "./utils.js";

/**
 * Reverse index for a backref field: parent id -> the relation records pointing
 * at it through `inverseField`.
 *
 * Maintained INCREMENTALLY. The previous implementation dropped the whole index
 * on any create/update/delete of the relation model and rebuilt it by scanning
 * every record of that model on the next read, so a workload that interleaves
 * writes with reads paid a full O(N) scan per write. Two production call sites
 * make that pathological: pos_loyalty puts a backLink on `pos.order.line`
 * inside an IndexedDB purge condition (evaluated per loyalty.card on every
 * debounced local sync), and pos_restaurant resolves a table's order through a
 * backLink on `pos.order`.
 *
 * `parentsByChild` is what makes removal possible without a scan: on delete the
 * record is already gone from the store, so its former parent ids can no longer
 * be read from RAW_SYMBOL.
 */
export class BackLinkIndex {
    constructor(store, relation, inverseField, onMembershipChange) {
        this.store = store;
        this.relation = relation;
        this.inverseField = inverseField;
        this.onMembershipChange = onMembershipChange;
        this.byParent = new Map();
        this.parentsByChild = new Map();
        // Buckets are ordered by the record store's insertion order, which the
        // full-rescan implementation produced for free and which callers rely
        // on. A per-child sequence, assigned once and kept across re-parenting,
        // reproduces it: a record that drops its parent and takes it again
        // returns to its original position instead of jumping to the end.
        this.seqByChild = new Map();
        this.nextSeq = 0;

        for (const child of store.getRecordsMap(relation, "id").values()) {
            // Sequence every record, not just the ones that currently have a
            // parent: a record whose inverse field is empty at build time and
            // is filled later must still sort into its store position rather
            // than land at the end of the bucket.
            this._seqOf(child.id);
            this._attach(child);
        }
    }

    get(parentId) {
        return this.byParent.get(parentId) || [];
    }

    onCreate(ids) {
        let changed = false;
        for (const id of ids || []) {
            this._seqOf(id);
            changed = this._reindex(id) || changed;
        }
        if (changed) {
            this.onMembershipChange();
        }
    }

    /**
     * A write that does not touch the inverse field cannot move the record
     * between buckets — skipping it is the whole point of the index. Consumers
     * that read other fields of the returned records subscribe to those records
     * directly, so they still re-render without a version bump here.
     */
    onUpdate(id, fields) {
        if (fields && !fields.includes(this.inverseField)) {
            return;
        }
        if (this._reindex(id)) {
            this.onMembershipChange();
        }
    }

    onDelete(id) {
        const changed = this._detach(id);
        // Only a real deletion retires the sequence; _detach alone must not, or
        // re-parenting would reorder the bucket.
        this.seqByChild.delete(id);
        if (changed) {
            this.onMembershipChange();
        }
    }

    onParentDeleted(parentId) {
        const bucket = this.byParent.get(parentId);
        if (!bucket) {
            return;
        }
        for (const child of bucket) {
            const parentIds = this.parentsByChild.get(child.id);
            if (!parentIds) {
                continue;
            }
            const remaining = parentIds.filter((id) => id !== parentId);
            if (remaining.length) {
                this.parentsByChild.set(child.id, remaining);
            } else {
                this.parentsByChild.delete(child.id);
            }
        }
        this.byParent.delete(parentId);
        this.onMembershipChange();
    }

    _parentIdsOf(child) {
        const value = child[RAW_SYMBOL][this.inverseField];
        if (value instanceof Set) {
            return [...value].filter(Boolean);
        }
        return value ? [value] : [];
    }

    _reindex(id) {
        const detached = this._detach(id);
        const child = this.store.getById(this.relation, id);
        const attached = child ? this._attach(child) : false;
        return detached || attached;
    }

    _attach(child) {
        const parentIds = this._parentIdsOf(child);
        if (!parentIds.length) {
            return false;
        }
        const seq = this._seqOf(child.id);
        for (const parentId of parentIds) {
            let bucket = this.byParent.get(parentId);
            if (!bucket) {
                bucket = [];
                this.byParent.set(parentId, bucket);
            }
            let at = bucket.length;
            while (at > 0 && this.seqByChild.get(bucket[at - 1].id) > seq) {
                at--;
            }
            bucket.splice(at, 0, child);
        }
        this.parentsByChild.set(child.id, parentIds);
        return true;
    }

    _seqOf(childId) {
        let seq = this.seqByChild.get(childId);
        if (seq === undefined) {
            seq = this.nextSeq++;
            this.seqByChild.set(childId, seq);
        }
        return seq;
    }

    _detach(childId) {
        const parentIds = this.parentsByChild.get(childId);
        if (!parentIds) {
            return false;
        }
        for (const parentId of parentIds) {
            const bucket = this.byParent.get(parentId);
            if (!bucket) {
                continue;
            }
            const at = bucket.findIndex((record) => record.id === childId);
            if (at !== -1) {
                bucket.splice(at, 1);
            }
            if (!bucket.length) {
                this.byParent.delete(parentId);
            }
        }
        this.parentsByChild.delete(childId);
        return true;
    }
}
