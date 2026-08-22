/** @odoo-module native */
import { RAW_SYMBOL } from "./utils.js";

export class BackLinkIndex {
    constructor(store, relation, inverseField, onMembershipChange) {
        this.store = store;
        this.relation = relation;
        this.inverseField = inverseField;
        this.onMembershipChange = onMembershipChange;
        this.byParent = new Map();
        this.parentsByChild = new Map();
        this.seqByChild = new Map();
        this.nextSeq = 0;

        for (const child of store.getRecordsMap(relation, "id").values()) {
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
