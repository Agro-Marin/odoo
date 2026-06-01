import { patchWithCleanup } from "@web/../tests/web_test_helpers";

const migrateCallbacks = {};

export function migrate(container, env) {
    for (const callback of Object.values(migrateCallbacks)) {
        callback(container, env);
    }
}

// `patchWithCleanup` registers its own teardown via HOOT's `after` hook, so the
// patch must be applied at the moment the test asks for it (typically the test
// body, before the migration runs). Wrapping it in `before` defers application
// to a suite-scoped phase that has already completed by the time the test body
// runs, leaving `migrateCallbacks` empty and silently skipping the migration.
export function setupMigrateFunctions(callbacks) {
    const newCallbacks = {};
    for (let i = 0; i < callbacks.length; i++) {
        newCallbacks[i] = callbacks[i];
    }
    patchWithCleanup(migrateCallbacks, newCallbacks);
}

// `HtmlUpgradeManager.upgrade()` resolves migration modules via
// `odoo.loader.modules.get(<spec>)`. Files under `/static/tests/` are
// deliberately excluded from `registerNativeModules` (see
// assetsbundle.py:1042 — test files are loaded via the import map only),
// so the lookup would return `undefined` and the upgrade silently no-ops
// inside the manager's catch-all. Register this module's namespace
// explicitly under the spec the registry stores so the upgrade pipeline
// finds it.
odoo.loader.modules.set("@html_editor/../tests/public/html_migrations_test_utils", {
    migrate,
    setupMigrateFunctions,
});
