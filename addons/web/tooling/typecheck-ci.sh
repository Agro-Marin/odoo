#!/usr/bin/env bash
#
# typecheck-ci.sh — ratcheting tsc gate for the web JS layer.
#
# Runs `tsc --noEmit` over the allowlisted files (tooling/typecheck-allowlist.txt)
# plus their transitive import graph, then fails ONLY when an error is attributed
# to an allowlisted file. Errors in imported-but-unlisted files are tolerated:
# they are the codebase's pre-existing type debt, removed file-by-file as each is
# cleaned and added to the allowlist.
#
# Usage:
#   bash tooling/typecheck-ci.sh              # gate: check every allowlisted file
#   bash tooling/typecheck-ci.sh --probe P    # report error count for one path P
#                                             # (use before adding P to the allowlist)
#
# Requirements: a local TypeScript install. Resolved in this order:
#   1. <community-root>/node_modules/.bin/tsc   (from tooling/enable.sh → npm install)
#   2. `npx --no-install tsc`
# Plus @types/luxon (declared in tooling/_package.json) for the luxon shim's types.
#
# Exit codes: 0 = all allowlisted files clean; 1 = a regression; 2 = setup error.

set -euo pipefail

TOOLING_DIR="$(cd -- "$(dirname "$0")" &>/dev/null && pwd)"
# Community (core) repo root, matching tooling/enable.sh's `cd ../../..`:
# .../addons/web/tooling -> up 3 -> the repo root that owns `addons/web`.
# (jsconfig.json + node_modules are installed here by enable.sh, and the
# jsconfig `@web/*` mapping is relative to this same root.)
ROOT="$(cd -- "$TOOLING_DIR/../../.." &>/dev/null && pwd)"
ALLOWLIST="$TOOLING_DIR/typecheck-allowlist.txt"
OWL_LOCAL="addons/web/static/lib/owl/owl.js"

# --- locate tsc ---------------------------------------------------------------
if [[ -x "$ROOT/node_modules/.bin/tsc" ]]; then
    TSC="$ROOT/node_modules/.bin/tsc"
elif command -v npx &>/dev/null; then
    TSC="npx --no-install tsc"
else
    echo "ERROR: no TypeScript found. Run tooling/enable.sh (npm install) first." >&2
    exit 2
fi

# --- resolve @types/luxon for the shim's type import --------------------------
# The luxon shim (core/l10n/luxon.js) imports luxon's types. @types/luxon is
# declared in tooling/_package.json and installed by enable.sh. Without it the
# shim would spuriously report TS2307, so fail loudly with a setup hint rather
# than blaming the file.
LUXON_TYPES="$ROOT/node_modules/@types/luxon"
if [[ ! -d "$LUXON_TYPES" ]]; then
    echo "ERROR: @types/luxon not found at $LUXON_TYPES." >&2
    echo "       Run tooling/enable.sh (or npm install @types/luxon) first." >&2
    exit 2
fi

# --- collect target files -----------------------------------------------------
mapfile -t FILES < <(grep -vE '^\s*#|^\s*$' "$ALLOWLIST")

PROBE_MODE=0
if [[ "${1:-}" == "--probe" ]]; then
    PROBE_MODE=1
    [[ -n "${2:-}" ]] || { echo "ERROR: --probe needs a file path" >&2; exit 2; }
    FILES=("$2")
fi

if [[ ${#FILES[@]} -eq 0 ]]; then
    echo "ERROR: allowlist is empty." >&2
    exit 2
fi

# --- generate a transient tsconfig (seam recipe: types:[] + local owl) --------
TMP_CFG="$(mktemp --suffix=.json)"
trap 'rm -f "$TMP_CFG"' EXIT

{
    printf '{\n  "compilerOptions": {\n'
    printf '    "moduleResolution": "node",\n'
    printf '    "baseUrl": "%s",\n' "$ROOT"
    printf '    "target": "ESNext", "module": "ESNext",\n'
    printf '    "noEmit": true, "allowJs": true, "checkJs": true,\n'
    printf '    "strict": false, "strictNullChecks": true, "skipLibCheck": true,\n'
    printf '    "lib": ["ESNext", "DOM", "DOM.Iterable"],\n'
    printf '    "types": [],\n'
    printf '    "paths": {\n'
    printf '      "luxon": ["%s"],\n' "$LUXON_TYPES"
    printf '      "@odoo/owl": ["%s"],\n' "$OWL_LOCAL"
    printf '      "@web/*": ["addons/web/static/src/*"]\n'
    printf '    }\n  },\n  "include": [\n'
    # Ambient type declarations — the global ``odoo`` (@types/odoo.d.ts) and
    # the ``services`` / ``registries`` modules (@types/services.d.ts,
    # @types/registries/*.d.ts) — back the IDE jsconfig via its typeRoots +
    # ``**/*.ts`` include. Mirror that here so files that use those ambient
    # types (registry, hooks, the service layer, …) validate against their
    # real declarations instead of spuriously failing on TS2304/TS2307.
    # ``skipLibCheck`` leaves the .d.ts themselves unchecked, and gate errors
    # are still filtered to the allowlisted files only, so this only ADDS
    # resolution — it never makes an already-clean file dirty.
    printf '    "%s/addons/web/static/src/@types/**/*.d.ts",\n' "$ROOT"
    for i in "${!FILES[@]}"; do
        sep=","; [[ $i -eq $((${#FILES[@]} - 1)) ]] && sep=""
        printf '    "%s/%s"%s\n' "$ROOT" "${FILES[$i]}" "$sep"
    done
    printf '  ]\n}\n'
} > "$TMP_CFG"

# --- run tsc (never let a nonzero tsc exit abort the script) ------------------
# Run from $ROOT so tsc prints error paths repo-relative ("addons/web/static/...")
# to match the allowlist entries. Historically tsc was run from the tooling cwd,
# so it emitted "../static/..." which the allowlist-path filter below never
# matched — the gate silently passed regardless of real errors. The suffix match
# below is a second line of defense if the cwd ever shifts again.
set +e
TSC_OUT="$(cd "$ROOT" && $TSC --project "$TMP_CFG" 2>&1)"
set -e

# --- filter errors to the target files ---------------------------------------
# Match on the cwd-independent path suffix from "static/" (a full, unique tail
# of each allowlisted path) so the comparison is robust to tsc's cwd. The "("
# anchor pins the match to the start of tsc's "(line,col)" so one file's suffix
# cannot match a longer path that merely ends with the same characters.
fail=0
for f in "${FILES[@]}"; do
    # strip the leading "addons/<module>/" -> "static/src/.../file.js"
    suffix="${f#addons/*/}"
    matches="$(printf '%s\n' "$TSC_OUT" | grep -F "$suffix(" || true)"
    if [[ -n "$matches" ]]; then
        fail=1
        echo "✗ $f"
        printf '%s\n' "$matches" | sed 's/^/    /'
    elif [[ $PROBE_MODE -eq 1 ]]; then
        echo "✓ $f — 0 errors (safe to add to the allowlist)"
    fi
done

if [[ $PROBE_MODE -eq 1 ]]; then
    exit $fail
fi

if [[ $fail -eq 1 ]]; then
    echo ""
    echo "TYPECHECK GATE FAILED: an allowlisted file regressed. Fix the errors"
    echo "above, or (if intentional) remove the file from typecheck-allowlist.txt."
    exit 1
fi

echo "✓ typecheck gate passed — ${#FILES[@]} allowlisted files are tsc-clean."
exit 0
