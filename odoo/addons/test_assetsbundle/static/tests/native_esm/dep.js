/** @odoo-module native */

// Fixture for the esbuild end-to-end test. Under static/tests/ rather than
// static/src/, for two reasons: url_to_module_path only accepts src/lib/tests,
// and static/src/*/** is what the manifest1..3 glob bundles enumerate, so a
// file added there silently joins them (see static/invalid_src/scss/).
export const DEP = 41;

export function bump(value) {
    return value + 1;
}
