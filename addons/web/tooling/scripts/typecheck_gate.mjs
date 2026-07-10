#!/usr/bin/env node
// @ts-check

/**
 * typecheck_gate.mjs — strict-ratcheting CI gate for tsc.
 *
 * The Odoo fork has ~613 of 615 source files annotated with @ts-check
 * but the codebase emits 7,500+ pre-existing strict-null errors that
 * would break CI on day one if `tsc --noEmit` were gated naively.
 * This script implements the standard "strict ratcheting" pattern
 * (Sentry, MS Teams, Webpack all use variants):
 *
 *   1. A baseline JSON file records, per (file, errorCode), the
 *      number of currently-tolerated errors.
 *   2. CI runs `tsc | typecheck_gate.mjs`.  If a PR introduces NEW
 *      errors (any (file, code) pair whose count exceeds the
 *      baseline), the gate exits 1 and prints the offenders.
 *   3. PRs that REMOVE errors pass and emit a hint ("baseline can be
 *      tightened — re-run with --update-baseline").
 *   4. `--update-baseline` regenerates the snapshot from the current
 *      tsc output.  PR review sees the baseline diff alongside the
 *      code change, so loosening the baseline requires a deliberate
 *      decision.
 *
 * Granularity rationale: per-line is too brittle (any line shift
 * drifts the baseline), per-message too noisy.  (File, code, count)
 * is robust to refactors that move lines around but still catches
 * real regressions.
 *
 * USAGE
 * -----
 *   # Gate (CI):
 *   tsc --noEmit -p jsconfig.json | node addons/web/tooling/scripts/typecheck_gate.mjs
 *
 *   # Refresh the baseline after a cleanup PR:
 *   tsc --noEmit -p jsconfig.json | node addons/web/tooling/scripts/typecheck_gate.mjs --update-baseline
 *
 *   # Use an explicit baseline path (e.g. enterprise has its own):
 *   ... | node typecheck_gate.mjs --baseline=path/to/other_baseline.json
 *
 * EXIT CODES
 * ----------
 *   0 — current state matches or beats baseline (no new violations)
 *   1 — at least one new (file, code) violation
 *   2 — usage error (missing baseline, malformed flags)
 */

import { readFileSync, writeFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const DEFAULT_BASELINE_PATH = resolve(__dirname, "typecheck_baseline.json");

// Standard tsc error format:
//   path/to/file.js(line,col): error TSnnnn: message text
// Continuation lines (multi-line diagnostics) start with whitespace
// and don't match — which is intentional, they're informational.
const ERROR_LINE_RE = /^(.+?)\((\d+),(\d+)\): error (TS\d+): (.+)$/;

const VIOLATION_PRINT_LIMIT = 50;

/**
 * Parse tsc output into per-file, per-error-code counts.
 * @param {string} text raw tsc stdout/stderr capture
 * @returns {Record<string, Record<string, number>>}
 */
function parseTscOutput(text) {
  /** @type {Record<string, Record<string, number>>} */
  const counts = {};
  for (const line of text.split("\n")) {
    const m = ERROR_LINE_RE.exec(line);
    if (!m) {
      continue;
    }
    const [, file, , , code] = m;
    counts[file] ??= {};
    counts[file][code] = (counts[file][code] || 0) + 1;
  }
  return counts;
}

/** @returns {number} */
function totalErrors(
  /** @type {Record<string, Record<string, number>>} */ counts,
) {
  let n = 0;
  for (const file of Object.values(counts)) {
    for (const k of Object.values(file)) {
      n += k;
    }
  }
  return n;
}

/**
 * Compare current state against baseline.  Returns NEW errors
 * (violations) and REMOVED errors (cleanups) keyed by (file, code).
 */
function compareCounts(
  /** @type {{files?: Record<string, Record<string, number>>}} */ baseline,
  /** @type {Record<string, Record<string, number>>} */ current,
) {
  /** @type {{file: string, code: string, baseline: number, current: number, delta: number}[]} */
  const violations = [];
  /** @type {{file: string, code: string, baseline: number, current: number, delta: number}[]} */
  const cleanups = [];
  const baseFiles = baseline.files || {};
  const allFiles = new Set([
    ...Object.keys(baseFiles),
    ...Object.keys(current),
  ]);
  for (const file of allFiles) {
    const before = baseFiles[file] || {};
    const after = current[file] || {};
    const allCodes = new Set([...Object.keys(before), ...Object.keys(after)]);
    for (const code of allCodes) {
      const b = before[code] || 0;
      const a = after[code] || 0;
      if (a > b) {
        violations.push({ file, code, baseline: b, current: a, delta: a - b });
      } else if (a < b) {
        cleanups.push({ file, code, baseline: b, current: a, delta: b - a });
      }
    }
  }
  return { violations, cleanups };
}

/**
 * Write a stable, sorted-key JSON baseline.  Stable key order means
 * baseline diffs in PRs reflect real changes, not key reshuffling.
 */
function writeBaseline(
  /** @type {string} */ path,
  /** @type {Record<string, Record<string, number>>} */ counts,
) {
  /** @type {Record<string, Record<string, number>>} */
  const sortedFiles = {};
  for (const file of Object.keys(counts).sort()) {
    /** @type {Record<string, number>} */
    const sortedCodes = {};
    for (const code of Object.keys(counts[file]).sort()) {
      sortedCodes[code] = counts[file][code];
    }
    sortedFiles[file] = sortedCodes;
  }
  const data = {
    _generated_at: new Date().toISOString().slice(0, 10),
    _total_errors: totalErrors(counts),
    _file_count: Object.keys(sortedFiles).length,
    _generator:
      "addons/web/tooling/scripts/typecheck_gate.mjs --update-baseline",
    files: sortedFiles,
  };
  writeFileSync(path, JSON.stringify(data, null, 2) + "\n");
  return data;
}

/** @param {string[]} argv */
function parseArgs(argv) {
  let baselinePath = DEFAULT_BASELINE_PATH;
  let update = false;
  for (const arg of argv) {
    if (arg === "--update-baseline") {
      update = true;
    } else if (arg.startsWith("--baseline=")) {
      baselinePath = resolve(arg.slice("--baseline=".length));
    } else if (arg === "--help" || arg === "-h") {
      console.log(
        "Usage:\n" +
          "  tsc | typecheck_gate.mjs                  # gate against default baseline\n" +
          "  tsc | typecheck_gate.mjs --update-baseline # regenerate baseline\n" +
          "  tsc | typecheck_gate.mjs --baseline=PATH   # use a different baseline file",
      );
      process.exit(0);
    } else {
      console.error(`Unknown argument: ${arg}. Pass --help for usage.`);
      process.exit(2);
    }
  }
  return { baselinePath, update };
}

function main() {
  const { baselinePath, update } = parseArgs(process.argv.slice(2));
  // Read full tsc output from stdin.  fd 0 read works for both
  // piped input and `< file` redirection.
  const tscOutput = readFileSync(0, "utf-8");
  const current = parseTscOutput(tscOutput);
  const total = totalErrors(current);
  const fileCount = Object.keys(current).length;

  if (update) {
    const data = writeBaseline(baselinePath, current);
    console.log(
      `✓ Baseline updated: ${data._total_errors} errors across ${data._file_count} files`,
    );
    console.log(`  Written to ${baselinePath}`);
    process.exit(0);
  }

  /** @type {{files?: Record<string, Record<string, number>>, _generated_at?: string, _total_errors?: number}} */
  let baseline;
  try {
    baseline = JSON.parse(readFileSync(baselinePath, "utf-8"));
  } catch (e) {
    console.error(`✗ Could not read baseline at ${baselinePath}.`);
    console.error(`  Reason: ${/** @type {Error} */ (e).message}`);
    console.error(`  Run with --update-baseline to create one.`);
    process.exit(2);
    return;
  }

  const { violations, cleanups } = compareCounts(baseline, current);

  if (violations.length) {
    const newErrorCount = violations.reduce((sum, v) => sum + v.delta, 0);
    console.error(
      `✗ ${newErrorCount} new typecheck error(s) across ${violations.length} (file, code) pair(s) vs baseline:`,
    );
    console.error(
      `  baseline @ ${baseline._generated_at}: ${baseline._total_errors} errors`,
    );
    console.error(`  current: ${total} errors across ${fileCount} files\n`);
    for (const v of violations.slice(0, VIOLATION_PRINT_LIMIT)) {
      console.error(
        `  ${v.file}: ${v.code}: ${v.baseline} → ${v.current} (+${v.delta})`,
      );
    }
    if (violations.length > VIOLATION_PRINT_LIMIT) {
      console.error(
        `  ...and ${violations.length - VIOLATION_PRINT_LIMIT} more`,
      );
    }
    process.exit(1);
  }

  if (cleanups.length) {
    const cleanupCount = cleanups.reduce((sum, c) => sum + c.delta, 0);
    console.log(
      `✓ No new violations. ${cleanupCount} error(s) cleaned up vs baseline ` +
        `in ${cleanups.length} (file, code) pair(s).`,
    );
    console.log(`  Run with --update-baseline to tighten.`);
  } else {
    console.log(
      `✓ No new violations. ${total} errors match baseline (${fileCount} files).`,
    );
  }
  process.exit(0);
}

main();
