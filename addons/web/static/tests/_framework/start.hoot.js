// @ts-check

import {
    __debug__,
    definePreset,
    defineTags,
    describe,
    isHootReady,
    start,
} from "@odoo/hoot";

import { patchBrowserLocation, patchBrowserStorage } from "./mock_browser.hoot.js";
import { setupTestEnvironment } from "./module_set.hoot.js";

/**
 * HOOT's job-id hash (``hoot_utils.js::generateHash``), reimplemented rather
 * than imported: ``@odoo/hoot`` lives in ``web.assets_unit_tests_setup`` while
 * this file lives in ``web.assets_unit_tests``, and the two bundles are cached
 * separately — importing across them breaks with "does not provide an export
 * named ..." whenever only one has been rebuilt. Same algorithm as
 * ``hoot_lib.generate_hash`` and ``test_js.py::_generate_hash``.
 *
 * @param {string} value
 * @returns {string}
 */
function _hashJobId(value) {
    let hash = 0;
    for (let i = 0; i < value.length; i++) {
        hash = (hash << 5) - hash + value.charCodeAt(i);
        hash |= 0;
    }
    return (hash + 16 ** 8).toString(16).slice(-8);
}

// Read before patchBrowserLocation() swaps the location object out.
const REQUESTED_IDS = new Set(
    new URLSearchParams(globalThis.location?.search ?? "")
        .getAll("id")
        .filter((id) => !id.startsWith("-")),
);

/** @param {any} test */
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

setupTestEnvironment();

patchBrowserLocation();
patchBrowserStorage();

/**
 * Disarm the module loader's production asset-recovery reload for the whole run.
 *
 * `handleAssetLoadError` reloads the page when a `<script>`/`<link>` under
 * `/web/assets/` fails, on the assumption that a stale bundle reference is
 * recoverable. Tests that exercise the `loadJS`/`loadCSS` failure paths request
 * URLs under exactly that prefix on purpose, so the recovery fires ON A TEST
 * RUNNER and reloads the whole HOOT page — which restarts the run from zero,
 * hits the same test again, and loops.
 *
 * Its once-per-60s `sessionStorage` guard cannot hold here: the runner mocks
 * both storage and the clock per test, so `now - last` is compared across two
 * different time bases. The loop is invisible in a short run (the guard happens
 * to hold) and fatal in a long one — `@web/core` restarted 918 times and never
 * reached a summary, failing `WebSuite.test_core` on a 900s timeout.
 *
 * `_reloadPage` exists as a seam documented "overridden in tests", but only
 * `module_loader.test.js` ever overrode it, and only on loader instances it
 * built itself — never the global one every other test shares.
 */
odoo.loader._reloadPage = () => {};

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
 * Narrow ``testSpecifiers`` to the test files an ``&id=`` filter can possibly
 * select, so a filtered run stops paying for every other file in the bundle.
 *
 * Every job a file registers is nested under that file's synthetic suite (see
 * ``_importInFileSuite``), so a job's ``fullName`` always starts with the
 * file's suite name. An id therefore selects a file only if it hashes one of
 * that suite name's ancestors — ``@web``, ``@web/core``, ``@web/core/domain``
 * for ``@web/core/domain``.
 *
 * The reverse case — an id naming a job *inside* a file (a nested
 * ``describe``, or a single test) — cannot be recognised from the hash alone,
 * so when nothing matches we import everything rather than run zero tests.
 * Non-test modules (helpers registering global hooks) are never filtered.
 *
 * @param {string[]} testSpecifiers
 * @returns {string[]}
 */
function _selectTestSpecifiers(testSpecifiers) {
    if (!REQUESTED_IDS.size) {
        return testSpecifiers;
    }
    const isSelected = (/** @type {any} */ specifier) => {
        if (!specifier.endsWith(".test")) {
            return true;
        }
        const parts = _suiteNameFromSpecifier(specifier).split("/");
        return parts.some((_, i) =>
            REQUESTED_IDS.has(_hashJobId(parts.slice(0, i + 1).join("/"))),
        );
    };
    const selected = testSpecifiers.filter(isSelected);
    return selected.some((specifier) => specifier.endsWith(".test"))
        ? selected
        : testSpecifiers;
}

/**
 * Fetch the modules ``loadAndStart`` is about to import, in parallel.
 *
 * The imports themselves must stay serial (each file's top-level code has to
 * see only its own suite on the stack), so without this every file costs a
 * round trip. The server no longer emits these links because it cannot see the
 * page's ``&id=`` filter; the URLs come from the import map it did emit.
 *
 * @param {string[]} specifiers
 */
function _preloadTestModules(specifiers) {
    const importMap = document.querySelector('script[type="importmap"]');
    if (!importMap?.textContent) {
        return;
    }
    let imports;
    try {
        imports = JSON.parse(importMap.textContent).imports;
    } catch {
        return;
    }
    if (!imports) {
        return;
    }
    const fragment = document.createDocumentFragment();
    for (const specifier of specifiers) {
        const href = imports[specifier];
        if (!href) {
            continue;
        }
        const link = document.createElement("link");
        link.rel = "modulepreload";
        link.href = href;
        fragment.append(link);
    }
    document.head.append(fragment);
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
 * @param {string[]} allTestSpecifiers - import map specifiers for test files
 */
export async function loadAndStart(allTestSpecifiers) {
    await isHootReady;
    const testSpecifiers = _selectTestSpecifiers(allTestSpecifiers);
    _preloadTestModules(testSpecifiers);
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
            console.warn(
                `[HOOT][import-fail][x${specifiers.length}] [${typeName}] ${message}`,
            );
            if (stack) {
                const frames = String(stack).split("\n").slice(0, 8);
                for (const f of frames) {
                    if (f.trim()) {
                        console.warn(`[HOOT][import-fail]   @ ${f.trim()}`);
                    }
                }
            } else {
                console.warn(`[HOOT][import-fail]   stack: <none>`);
            }
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
