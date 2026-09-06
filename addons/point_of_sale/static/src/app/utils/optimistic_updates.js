const snapshot = (value) => (Array.isArray(value) ? [...value] : value);

export class OptimisticUpdates {
    constructor(model) {
        this.model = model;
        this.records = new Map();
        this.pending = 0;
    }

    apply(records, values) {
        if (!this.pending++) {
            this.unsubscribe = this.model.addEventListener(
                "update",
                ({ id, fields }) => {
                    const record = this.model.get(id);
                    const tracked = this.records.get(record);
                    for (const field of fields) {
                        if (!this.applying?.get(record)?.has(field)) {
                            tracked?.delete(field);
                        }
                    }
                },
            );
        }
        const changes = [];
        const fields = Object.keys(values).filter(
            (field) => field !== "id" && field !== "uuid" && this.model.fields[field],
        );
        const settle = (success) => {
            const updates = new Map();
            for (const { record, field, state, change } of changes) {
                const tracked = this.records.get(record);
                if (tracked?.get(field) !== state) {
                    continue;
                }
                change.pending = false;
                if (!success) {
                    const wasLatest = state.changes.at(-1) === change;
                    state.changes.splice(state.changes.indexOf(change), 1);
                    if (wasLatest && this.model.get(record.id) === record) {
                        if (!updates.has(record)) {
                            updates.set(record, {});
                        }
                        updates.get(record)[field] = state.changes.length
                            ? state.changes.at(-1).value
                            : state.original;
                    }
                }
                if (!state.changes.some((entry) => entry.pending)) {
                    tracked.delete(field);
                }
            }
            try {
                this.update(updates);
            } finally {
                if (!--this.pending) {
                    this.unsubscribe();
                    this.records.clear();
                }
            }
        };
        try {
            for (const record of records) {
                if (!this.records.has(record)) {
                    this.records.set(record, new Map());
                }
                const tracked = this.records.get(record);
                for (const field of fields) {
                    if (!tracked.has(field)) {
                        tracked.set(field, {
                            original: snapshot(record[field]),
                            changes: [],
                        });
                    }
                    const state = tracked.get(field);
                    const change = { pending: true };
                    state.changes.push(change);
                    changes.push({ record, field, state, change });
                }
            }
            this.update(new Map(records.map((record) => [record, values])));
            for (const { record, field, change } of changes) {
                change.value = snapshot(record[field]);
            }
        } catch (error) {
            settle(false);
            throw error;
        }
        return { commit: () => settle(true), rollback: () => settle(false) };
    }

    update(updates) {
        const previous = this.applying;
        this.applying = new Map(
            [...updates].map(([record, values]) => [
                record,
                new Set(Object.keys(values)),
            ]),
        );
        try {
            for (const [record, values] of updates) {
                record.update(values, { omitUnknownField: true });
            }
        } finally {
            this.applying = previous;
        }
    }
}
