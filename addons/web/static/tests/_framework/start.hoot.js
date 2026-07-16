// @ts-check

// ! WARNING: this module cannot depend on modules not ending with ".hoot" (except libs) !

import {
    __debug__,
    definePreset,
    defineTags,
    describe,
    isHootReady,
    start,
} from "@odoo/hoot";

import { patchBrowserLocation } from "./mock_browser.hoot.js";
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

// Wire ``browser.location`` to HOOT's ``mockLocation`` so navigation calls
// in tests (``redirect()``, ``router.pushState`` w/ reload, etc.) update an
// in-memory mock URL instead of triggering real ``window.location`` writes
// that would destroy the test runner page mid-suite.
patchBrowserLocation();

// Hoot exposes the runner via ``__debug__`` so we can push/pop the
// suiteStack around each test-file import — see ``_importInFileSuite``.
const _runner = /** @type {any} */ (__debug__);

/**
 * Convert a test specifier into the suite name HOOT's id-filter expects:
 * ``@bus/../tests/foo/bar.test`` → ``@bus/foo/bar`` (matches the pre-ESM
 * ``getSuitePath``/``describeDrySuite`` convention that ``WebSuite._run_hoot``
 * hashes into the ``&id=`` param). Keeping the ``@<addon>`` prefix is
 * critical — without it ``hash("@web/core")`` won't match the synthetic
 * suite ``web/core/...`` and HOOT refuses to run any filtered tests.
 *
 * @param {string} specifier
 * @returns {string}
 */
function _suiteNameFromSpecifier(specifier) {
    const m = specifier.match(/^(@[^/]+)\/\.\.\/tests\/(.*?)(?:\.test)?$/);
    return m ? `${m[1]}/${m[2]}` : specifier;
}

/**
 * Import a single test file inside a synthetic per-file suite.
 *
 * Hoot requires every ``test()`` to live under a parent suite (see
 * ``runner.addTest``: throws "cannot register a test outside of a
 * suite").  Test files written before the ESM refactor relied on the
 * pre-existing ``describeDrySuite`` helper to wrap each file in a
 * ``describe(suitePath, () => startModule(file))`` block.  The new
 * ``import(spec)``-based loader dropped that wrapping.
 *
 * Restoring it via ``describe(name, () => import(...))`` doesn't work
 * because ``describe`` runs its callback synchronously and pops the
 * suite before ``import()`` resolves.  Instead we:
 *
 *   1. Create the file's suite with an empty ``describe`` callback —
 *      this registers the suite in ``runner.rootSuites`` and pops it
 *      from the stack.
 *   2. Push the captured suite back onto ``runner.suiteStack`` so the
 *      imported module's top-level code sees it as the current parent.
 *   3. ``await import(spec)``.
 *   4. Pop the suite in a ``finally`` so we don't leak stack state on
 *      error.
 *
 * Imports must run **serially** so each file's top-level code sees
 * only its own suite on the stack — concurrent imports would
 * interleave pushes/pops and bind tests to the wrong file's suite.
 *
 * @param {string} specifier
 */
async function _importInFileSuite(specifier) {
    const suiteName = _suiteNameFromSpecifier(specifier);
    /** @type {any} */
    let fileSuite;
    describe(suiteName, () => {
        fileSuite = _runner.suiteStack.at(-1);
    });
    if (!fileSuite) {
        // Should never happen — describe() always pushes a suite — but
        // if HOOT internals change, fall back to the raw import so the
        // error surfaces at the file's top-level call site instead of
        // here.
        return import(specifier);
    }
    _runner.suiteStack.push(fileSuite);
    try {
        return await import(specifier);
    } finally {
        _runner.suiteStack.pop();
    }
}

/**
 * Load all test modules via native ESM import() and start the Hoot runner.
 *
 * Each file's import runs inside a synthetic per-file suite (see
 * ``_importInFileSuite``) so legacy-style test files (top-level
 * ``test()`` / ``describe.current.tags(...)``) work without rewrites.
 *
 * Called by the bridge script generated in ir_qweb.py.
 *
 * @param {string[]} testSpecifiers - import map specifiers for test files
 */
export async function loadAndStart(testSpecifiers) {
    await isHootReady;
    // SERIAL load to keep the suiteStack consistent across imports.
    // Bundles are pre-fetched (esbuild output + import-map satellites
    // are already in browser cache by the time we get here), so the
    // serial cost is dominated by module-evaluation, not network I/O.
    /** @type {Array<{status: "fulfilled" | "rejected", value?: any, reason?: any}>} */
    const results = [];
    for (const spec of testSpecifiers) {
        try {
            const value = await _importInFileSuite(spec);
            results.push({ status: "fulfilled", value });
        } catch (e) {
            results.push({ status: "rejected", reason: e });
        }
    }
    const failed = results
        .map((r, i) => ({ result: r, specifier: testSpecifiers[i] }))
        .filter(({ result }) => result.status === "rejected");
    if (failed.length) {
        // Group failures by error message (not by specifier) so a single
        // underlying bug doesn't appear as 300 near-identical log lines;
        // keep the first occurrence's full reason (message, type, stack,
        // cause chain — it may be wrapped, e.g. in a HootError) as the
        // actionable summary, with the full specifier list beneath it.
        const grouped = new Map();
        for (const { result, specifier } of failed) {
            const reason = result.reason;
            const key = reason?.message || String(reason);
            const bucket = grouped.get(key);
            if (bucket) {
                bucket.specifiers.push(specifier);
            } else {
                let typeName;
                try {
                    typeName =
                        reason?.constructor?.name ||
                        (reason === null ? "null" : typeof reason);
                } catch {
                    typeName = "(thrown-during-introspection)";
                }
                const stack = reason?.stack || "";
                // Walk the cause chain so wrapped errors don't lose the
                // root site.  ``cause`` is standard on Error in modern
                // browsers; HOOT also uses it for re-throws.
                const causes = [];
                let cur = reason?.cause;
                let depth = 0;
                while (cur && depth < 5) {
                    causes.push({
                        type: cur?.constructor?.name || typeof cur,
                        message: cur?.message || String(cur),
                        stack: cur?.stack || "",
                    });
                    cur = cur?.cause;
                    depth++;
                }
                grouped.set(key, {
                    specifiers: [specifier],
                    typeName,
                    stack,
                    causes,
                });
            }
        }
        console.warn(
            `[HOOT] ${failed.length}/${testSpecifiers.length} test modules failed to import; ${grouped.size} unique error(s)`,
        );
        for (const [message, { specifiers, typeName, stack, causes }] of grouped) {
            // First-line summary per group: count + type + message.
            // Type prefix ("TypeError" vs "HootError" vs "Object") lets
            // a developer tell at a glance whether the failure is a JS
            // runtime error, a HOOT registration error, or a thrown
            // primitive (which would have no stack).
            console.warn(
                `[HOOT][import-fail][x${specifiers.length}] [${typeName}] ${message}`,
            );
            // Stack from the FIRST failing specifier in the group.
            // For "X / 132 failed with the same message" cases this
            // pinpoints the shared culprit (e.g. a top-level call in a
            // common helper) without bloating the log with N copies.
            if (stack) {
                // Each stack frame on its own log line so the
                // browser→Python bridge doesn't truncate at the first
                // newline.  Cap at 8 frames per group — the top frames
                // are the actionable ones.
                const frames = String(stack).split("\n").slice(0, 8);
                for (const f of frames) {
                    if (f.trim()) {
                        console.warn(`[HOOT][import-fail]   @ ${f.trim()}`);
                    }
                }
            } else {
                // Some thrown values (strings, plain objects, frozen
                // errors) don't carry a stack — surface that explicitly
                // so it's not mistaken for "we forgot to capture it".
                console.warn(`[HOOT][import-fail]   stack: <none>`);
            }
            // Wrapped causes appear when HOOT re-throws an inner error;
            // log up to the first 3 levels so the original site is
            // visible.  Most chains are 1 deep (HootError wrapping a
            // TypeError), so 3 is generous.
            for (let i = 0; i < Math.min(causes.length, 3); i++) {
                const c = causes[i];
                console.warn(
                    `[HOOT][import-fail]   cause[${i}]: [${c.type}] ${c.message}`,
                );
                if (c.stack) {
                    const causeFrames = String(c.stack).split("\n").slice(0, 6);
                    for (const f of causeFrames) {
                        if (f.trim()) {
                            console.warn(
                                `[HOOT][import-fail]   cause[${i}] @ ${f.trim()}`,
                            );
                        }
                    }
                }
            }
            for (const spec of specifiers.slice(0, 5)) {
                console.warn(`[HOOT][import-fail]   - ${spec}`);
            }
            if (specifiers.length > 5) {
                console.warn(
                    `[HOOT][import-fail]   ... +${specifiers.length - 5} more`,
                );
            }
        }
    }
    start();
}
