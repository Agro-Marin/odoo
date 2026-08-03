import { patchWithCleanup } from "@web/../tests/web_test_helpers";

const migrateCallbacks = {};

export function migrate(container, env) {
    for (const callback of Object.values(migrateCallbacks)) {
        callback(container, env);
    }
}

// `patchWithCleanup` registers its teardown via HOOT's `after` hook, so callers
// must patch from the test body: doing it in `before` leaves `migrateCallbacks`
// empty by the time the test runs, silently skipping the migration.
export function setupMigrateFunctions(callbacks) {
    const newCallbacks = {};
    for (let i = 0; i < callbacks.length; i++) {
        newCallbacks[i] = callbacks[i];
    }
    patchWithCleanup(migrateCallbacks, newCallbacks);
}

// `HtmlUpgradeManager.upgrade()` resolves migration modules through
// `odoo.loader.modules.get(<spec>)`, and `/static/tests/` files are excluded
// from `registerNativeModules` (odoo/tools/assets/esbuild.py), so the lookup
// would return `undefined` and the upgrade would silently no-op. Register this
// module under the spec the upgrade registry stores.
odoo.loader.modules.set("@html_editor/../tests/public/html_migrations_test_utils", {
    migrate,
    setupMigrateFunctions,
});
