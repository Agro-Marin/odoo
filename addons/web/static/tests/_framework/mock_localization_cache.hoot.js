// @ts-check

import { afterEach, beforeEach } from "@odoo/hoot";

const LOCALIZATION_DB = "localization";

export function isolateLocalizationCache() {
    /** @type {Record<string, any> | null} */
    let originalMethods = null;

    beforeEach(() => {
        const indexedDbModule = odoo.loader.modules.get("@web/core/utils/indexed_db");
        if (!indexedDbModule?.IndexedDB) {
            return;
        }
        const proto = indexedDbModule.IndexedDB.prototype;
        originalMethods = { read: proto.read, write: proto.write };
        const { read, write } = originalMethods;
        proto.read = async function (/** @type {any} */ table, /** @type {any} */ key) {
            if (this.name === LOCALIZATION_DB) {
                return undefined;
            }
            return read.call(this, table, key);
        };
        proto.write = async function (
            /** @type {any} */ table,
            /** @type {any} */ key,
            /** @type {any} */ value,
        ) {
            if (this.name === LOCALIZATION_DB) {
                return undefined;
            }
            return write.call(this, table, key, value);
        };
    });

    afterEach(() => {
        if (!originalMethods) {
            return;
        }
        const indexedDbModule = odoo.loader.modules.get("@web/core/utils/indexed_db");
        if (indexedDbModule?.IndexedDB) {
            Object.assign(indexedDbModule.IndexedDB.prototype, originalMethods);
        }
        originalMethods = null;
    });
}
