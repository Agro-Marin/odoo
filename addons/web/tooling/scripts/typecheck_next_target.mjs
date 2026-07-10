#!/usr/bin/env node
// @ts-check

/**
 * typecheck_next_target.mjs — rank baseline files by cleanup leverage.
 *
 * Removes friction from the "cleanup hour" cadence: rather than asking
 * "what should I fix?" each session, this script reads the current
 * baseline and prints the top N candidates ordered by (estimated
 * impact × estimated ease).  The team picks one, fixes it, updates
 * the baseline (`typecheck_gate.mjs --update-baseline`), and the next
 * picker run automatically reflects the new state.
 *
 * Heuristic
 * ---------
 *   score(file) = total_errors × average_ease(error_codes)
 *   • Production code default; --include-tests opt-in (test mocks are
 *     inherently loose and clean up less productively).
 *   • Per-code ease scores calibrated from the monetary_field.js
 *     cleanup (2026-05-06): nullability errors are nearly always
 *     1-line guards or class-field declarations; TS2345/TS2339 take
 *     real refactoring.
 *
 * Usage
 * -----
 *   node typecheck_next_target.mjs                  # top 10 production files
 *   node typecheck_next_target.mjs --limit=20       # top 20
 *   node typecheck_next_target.mjs --include-tests  # include test/*.test.js
 *   node typecheck_next_target.mjs --code=TS18047   # only files dominated by this code
 *   node typecheck_next_target.mjs --baseline=PATH  # alternate baseline (e.g. enterprise)
 */

import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const DEFAULT_BASELINE_PATH = resolve(__dirname, "typecheck_baseline.json");

/**
 * Per-error-code ease score in [0, 1].  Higher = easier to fix in
 * isolation.  Defaults to 0.5 for codes not listed (unknown ease).
 *
 * Bucket rationale:
 *   1.0 — null/undefined narrowing.  Usually a one-line guard, a `?.`,
 *         or a class-field declaration.  Behavior-preserving.
 *   0.9 — broken module reference.  Often a stale JSDoc `import("...")`.
 *   0.7 — type assignment mismatch.  Sometimes a JSDoc tweak, sometimes
 *         a real type inconsistency.
 *   0.5 — argument count mismatch.  Caller invokes with wrong arity;
 *         needs signature understanding.
 *   0.4 — property does not exist.  Either missing in declared schema
 *         or accessing through wrong type.  Real type work.
 */
const EASE_BY_CODE = {
  TS18047: 1.0, // 'X' is possibly 'null'
  TS18048: 1.0, // 'X' is possibly 'undefined'
  TS2531: 1.0, // Object is possibly 'null'
  TS2532: 1.0, // Object is possibly 'undefined'
  TS2538: 0.9, // Type cannot be used as index type — often null narrowing
  TS2307: 0.9, // Cannot find module — often broken JSDoc import
  TS2322: 0.7, // Type X is not assignable to type Y
  TS2820: 0.7, // Did you mean Z (typo-style)
  TS2820_TYPO: 0.7, // alias placeholder
  TS2353: 0.6, // Object literal may only specify known properties
  TS2345: 0.5, // Argument of type X is not assignable
  TS2554: 0.5, // Expected N arguments, but got M
  TS2693: 0.5, // 'X' only refers to a type but used as value
  TS2769: 0.5, // No overload matches
  TS2810: 0.5, // Expected 1 argument, but got 0 (Promise constructor)
  TS18042: 0.7, // Type cannot be imported in JS files
  TS2339: 0.4, // Property does not exist on type
  TS2551: 0.4, // Property does not exist (typo suggestion)
  TS2694: 0.4, // Namespace X has no exported member Y
};

const DEFAULT_EASE = 0.5;

/**
 * @param {Record<string, number>} codes
 * @returns {number} weighted average ease in [0, 1]
 */
function avgEase(codes) {
  let weightedSum = 0;
  let total = 0;
  for (const [code, count] of Object.entries(codes)) {
    weightedSum += (EASE_BY_CODE[code] ?? DEFAULT_EASE) * count;
    total += count;
  }
  return total > 0 ? weightedSum / total : 0;
}

/** @param {string} file */
function isTest(file) {
  return file.includes("/tests/") || file.endsWith(".test.js");
}

/** @param {string[]} argv */
function parseArgs(argv) {
  let limit = 10;
  let includeTests = false;
  /** @type {string | null} */
  let codeFilter = null;
  let baselinePath = DEFAULT_BASELINE_PATH;
  for (const arg of argv) {
    if (arg === "--include-tests") {
      includeTests = true;
    } else if (arg.startsWith("--limit=")) {
      limit = parseInt(arg.slice("--limit=".length), 10);
    } else if (arg.startsWith("--code=")) {
      codeFilter = arg.slice("--code=".length);
    } else if (arg.startsWith("--baseline=")) {
      baselinePath = resolve(arg.slice("--baseline=".length));
    } else if (arg === "--help" || arg === "-h") {
      console.log(
        "Usage: node typecheck_next_target.mjs [--limit=N] [--include-tests] [--code=TSnnnn] [--baseline=PATH]",
      );
      process.exit(0);
    } else {
      console.error(`Unknown argument: ${arg}`);
      process.exit(2);
    }
  }
  return { limit, includeTests, codeFilter, baselinePath };
}

function main() {
  const { limit, includeTests, codeFilter, baselinePath } = parseArgs(
    process.argv.slice(2),
  );
  /** @type {{files: Record<string, Record<string, number>>, _total_errors: number}} */
  const baseline = JSON.parse(readFileSync(baselinePath, "utf-8"));

  const ranked = Object.entries(baseline.files)
    .filter(([f]) => includeTests || !isTest(f))
    .filter(([, codes]) => !codeFilter || codeFilter in codes)
    .map(([file, codes]) => {
      const errorCount = Object.values(codes).reduce((a, b) => a + b, 0);
      const ease = avgEase(codes);
      return {
        file,
        errorCount,
        ease,
        codes,
        score: errorCount * ease,
      };
    })
    .sort((a, b) => b.score - a.score)
    .slice(0, limit);

  const headerScope = includeTests ? "all files" : "production code only";
  const headerCode = codeFilter ? `, dominated by ${codeFilter}` : "";
  console.log(
    `Top ${ranked.length} cleanup targets (${headerScope}${headerCode})`,
  );
  console.log(`Baseline: ${baseline._total_errors} total errors`);
  console.log(`Score = errors × avg-ease;  ease scale [0.4..1.0]\n`);
  console.log("  score   errors   ease   file (top error codes)");
  console.log("  ------  -------  ------ ----------------------");
  for (const r of ranked) {
    const codeBreakdown = Object.entries(r.codes)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 4)
      .map(([c, n]) => `${c}×${n}`)
      .join(" ");
    const more =
      Object.keys(r.codes).length > 4
        ? ` +${Object.keys(r.codes).length - 4}`
        : "";
    console.log(
      `  ${r.score.toFixed(1).padStart(6)}  ${String(r.errorCount).padStart(7)}  ${r.ease.toFixed(2).padStart(6)} ${r.file}`,
    );
    console.log(`                          ${codeBreakdown}${more}`);
  }
  console.log(
    `\nTo clean up the top file: edit it, then re-run\n  tsc --noEmit -p jsconfig.json | node tooling/scripts/typecheck_gate.mjs --update-baseline`,
  );
}

main();
