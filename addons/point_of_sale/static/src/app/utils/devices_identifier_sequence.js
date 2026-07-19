/** @odoo-module native */
export default class DeviceIdentifierSequence {
    static uniqueDeviceIdentifierKey = `${odoo.access_token}-unique_device_identifier`;

    constructor({ orm }) {
        this.orm = orm;
        this.device_identifier = "";
    }

    /**
     * The shape every consumer can rely on. Used whenever nothing valid is
     * persisted (yet, or any more).
     */
    get defaultData() {
        return {
            device_identifier: this.device_identifier ?? "",
            next_number: 1,
            unsynced_number_stack: [],
        };
    }

    /**
     * Never returns null. `localStorage.getItem` yields null for a missing key
     * and `JSON.parse(null)` is null, so every `this.data.x` consumer below
     * used to throw a TypeError the moment the entry went away — which happens
     * whenever the user clears site data, storage is evicted, or another tab
     * resets it. `identifier` is read on EVERY order sync
     * (getSyncAllOrdersContext), so that turned a recoverable storage loss into
     * permanently broken syncing with an opaque error. Only saveUnusedNumber
     * guarded for it; the rest did not.
     */
    get data() {
        const localStorageKey = DeviceIdentifierSequence.uniqueDeviceIdentifierKey;
        let parsed;
        try {
            parsed = JSON.parse(localStorage.getItem(localStorageKey));
        } catch {
            // Corrupt blob: treat exactly like a missing one.
            parsed = null;
        }
        if (!parsed || typeof parsed !== "object") {
            return this.defaultData;
        }
        // Merge so a partially-written entry still exposes every key.
        return { ...this.defaultData, ...parsed };
    }

    get identifier() {
        const data = this.data;
        return data.device_identifier;
    }

    get unsyncedNumberStack() {
        const data = this.data;
        return data.unsynced_number_stack || [];
    }

    get nextNumber() {
        const data = this.data;
        return data.unsynced_number_stack.length
            ? data.unsynced_number_stack.sort((a, b) => a - b)[0]
            : data.next_number;
    }

    async initialize() {
        const localStorageKey = DeviceIdentifierSequence.uniqueDeviceIdentifierKey;
        const deviceIdentifier = localStorage.getItem(localStorageKey);

        if (!deviceIdentifier) {
            const data = await this.orm.call(
                "pos.config",
                "register_new_device_identifier",
                [odoo.pos_config_id],
            );

            this.device_identifier = data.device_identifier;
            this.save({
                device_identifier: data.device_identifier,
                next_number: 1,
                unsynced_number_stack: [],
            });
        } else {
            // Also mirror an ALREADY-persisted identifier into memory. Without
            // this the in-memory copy stayed "" on every normal boot, so it
            // could not serve as the fallback when the storage entry later
            // disappears mid-session.
            this.device_identifier = this.data.device_identifier;
        }
    }

    getFirstUnsyncedNumber() {
        const unsyncedNumberStack = this.unsyncedNumberStack;
        const sorted = unsyncedNumberStack.sort((a, b) => a - b);
        if (sorted.length === 0) {
            return null;
        }

        this.save({
            device_identifier: this.data.device_identifier,
            next_number: this.data.next_number,
            unsynced_number_stack: sorted.slice(1), // Remove the first element from the stack
        });

        return sorted[0];
    }

    useNext() {
        const unsyncedNumber = this.getFirstUnsyncedNumber();
        if (unsyncedNumber) {
            return unsyncedNumber;
        }

        const data = this.data;
        const number = data.next_number;
        const newData = {
            device_identifier: data.device_identifier,
            next_number: number + 1,
            unsynced_number_stack: [], // In case of order deletion, its identifier will be added to this stack to be reused later
        };

        this.save(newData);
        return number;
    }

    save({ next_number, device_identifier, unsynced_number_stack }) {
        const localStorageKey = DeviceIdentifierSequence.uniqueDeviceIdentifierKey;
        const current = this.data;
        const data = {
            device_identifier: device_identifier || current.device_identifier,
            next_number: next_number || current.next_number,
            unsynced_number_stack: [
                ...new Set(
                    unsynced_number_stack || current.unsynced_number_stack || [],
                ),
            ],
        };
        localStorage.setItem(localStorageKey, JSON.stringify(data));
    }

    saveUnusedNumber(orders) {
        const data = this.data;
        // `data` is now total, so guard on the thing that actually matters:
        // never persist a sequence under a blank device identifier (that would
        // collide with another device's stack). Compare against "" rather than
        // using falsiness — the identifier is numeric and 0 is legitimate.
        if (data.device_identifier === "" || data.device_identifier == null) {
            return;
        }
        const numbers = orders
            .filter((o) => !o.isSynced)
            .map((o) => this.extractNumberFromReference(o.pos_reference))
            // One malformed pos_reference would poison the stack with NaN,
            // which then corrupted the next-number sorting for the session.
            .filter(Number.isInteger);
        const unsyncedNumberStack = new Set([
            ...data.unsynced_number_stack,
            ...numbers,
        ]);

        this.save({
            device_identifier: data.device_identifier,
            next_number: data.next_number,
            unsynced_number_stack: Array.from(unsyncedNumberStack),
        });
    }

    extractNumberFromReference(reference) {
        return parseInt(reference.split("-")[2]);
    }
}
