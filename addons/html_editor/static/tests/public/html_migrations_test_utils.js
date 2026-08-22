import { patchWithCleanup } from "@web/../tests/web_test_helpers";

const migrateCallbacks = {};

export function migrate(container, env) {
    for (const callback of Object.values(migrateCallbacks)) {
        callback(container, env);
    }
}

export function setupMigrateFunctions(callbacks) {
    const newCallbacks = {};
    for (let i = 0; i < callbacks.length; i++) {
        newCallbacks[i] = callbacks[i];
    }
    patchWithCleanup(migrateCallbacks, newCallbacks);
}

odoo.loader.modules.set("@html_editor/../tests/public/html_migrations_test_utils", {
    migrate,
    setupMigrateFunctions,
});
