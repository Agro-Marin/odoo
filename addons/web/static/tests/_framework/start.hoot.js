// @ts-check

// ! WARNING: this module cannot depend on modules not ending with ".hoot" (except libs) !

import { definePreset, defineTags, isHootReady, start } from "@odoo/hoot";

import { setupTestEnvironment } from "./module_set.hoot.js";

function beforeFocusRequired(test) {
    if (!document.hasFocus()) {
        console.warn(
            "[FOCUS REQUIRED]",
            `test "${test.name}" requires focus inside of the browser window and will probably fail without it`,
        );
    }
}

definePreset("desktop", {
    icon: "fa-desktop",
    label: "Desktop",
    size: [1366, 768],
    tags: ["-mobile"],
    touch: false,
});
definePreset("mobile", {
    icon: "fa-mobile font-bold",
    label: "Mobile",
    size: [375, 667],
    tags: ["-desktop"],
    touch: true,
});
defineTags(
    {
        name: "desktop",
        exclude: ["headless", "mobile"],
    },
    {
        name: "mobile",
        exclude: ["desktop", "headless"],
    },
    {
        name: "headless",
        exclude: ["desktop", "mobile"],
    },
    {
        name: "focus required",
        before: beforeFocusRequired,
    },
);

// Setup test environment: patch registries, remove app-specific services.
setupTestEnvironment();

/**
 * Load all test modules via native ESM import() and start the Hoot runner.
 *
 * Follows Hoot's canonical pattern: import all test files (each calls
 * describe/test to register suites), then call start() once.  No
 * odoo.loader.factories, no Runner internal hacks.
 *
 * Called by the bridge script generated in ir_qweb.py.
 *
 * @param {string[]} testSpecifiers - import map specifiers for test files
 */
export async function loadAndStart(testSpecifiers) {
    await isHootReady;
    const results = await Promise.allSettled(testSpecifiers.map((s) => import(s)));
    const failed = results.filter((r) => r.status === "rejected");
    if (failed.length) {
        console.warn(
            `[HOOT] ${failed.length}/${testSpecifiers.length} test modules failed to import:`,
            failed.map((r) => r.reason?.message || r.reason).slice(0, 10),
        );
    }
    start();
}
