// @ts-check

import { afterEach, beforeEach } from "@odoo/hoot";

/**
 * Name of the database `localization_service` caches its translations in
 * (`new IndexedDB("localization", ...)`). Spelled out rather than imported:
 * this file lives in `web.assets_unit_tests_setup` and cannot import from the
 * bundle the service is in.
 */
const LOCALIZATION_DB = "localization";

/**
 * Make the translations cache always miss, so every test cold-boots it.
 *
 * IndexedDB is real in unit tests and shared by every test in the browser
 * profile, so whatever one test writes, later tests read. For most consumers
 * that is merely untidy. For `localization_service` it is a flake generator:
 * on a cache *hit* it serves the stored translations and fires a **background**
 * refresh whose rejection it only logs, and the read that decides this is a
 * real event-loop round trip. So the refresh routinely lands after the test
 * that triggered it has torn its mock server down -- at which point hoot's
 * `fetch` is unmocked, the request throws
 *
 *     Could not fetch "/web/webclient/translations?hash=...": cannot make a
 *     request when fetch is not mocked
 *
 * and the warning is charged to whichever test is running at that moment. The
 * test it fails has no relationship to the test that caused it. Observed as
 * `@mail/emoji` failing in roughly one full `@mail` run in three, always with
 * exactly one such warning in the log and never without one.
 *
 * Forcing the miss puts the fetch back on the cold-boot path, where the service
 * awaits it inside its own test's mock window. That is also the path a browser
 * with no cache takes, which is what a test starting from nothing should model.
 *
 * Scoped to this one database: every other consumer keeps the real IndexedDB.
 * Mocking the class wholesale was tried and is not viable -- suites have grown
 * to depend on real semantics the in-memory stand-in does not reproduce.
 */
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
        proto.read = async function (table, key) {
            if (this.name === LOCALIZATION_DB) {
                return undefined;
            }
            return read.call(this, table, key);
        };
        proto.write = async function (table, key, value) {
            if (this.name === LOCALIZATION_DB) {
                // Nothing reads it back, so skip the write rather than churn a
                // real database from every test in the suite.
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
