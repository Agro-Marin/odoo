#!/bin/bash
# Rebuild popper_compat.esm.js, the SELF-CONTAINED copy of
# web/static/src/libs/popper_compat.js served to standalone pages.
#
#   addons/web/static/lib/popper_compat/build.sh        # rebuild in place
#   addons/web/static/lib/popper_compat/build.sh --check # verify freshness
#
# Why a second copy exists: pages outside the asset pipeline (the IoT box
# homepage) load bootstrap.esm.js straight into the browser and resolve
# `@popperjs/core` through an import map. They have no bundler, so they cannot
# follow this module's `@web/...` imports. Bundled code does NOT use this file
# -- esbuild inlines the source instead (see _LIB_CANDIDATES) -- so the two can
# only drift if this build goes stale, which `--check` (wired into
# check_vendored_libs.py) exists to catch.
#
# Run from the `odoo` repo root, or let the script find it.
set -e
root="$(cd "$(dirname "$0")/../../../../.." && pwd)"
cd "$root"
src="addons/web/static/src/libs/popper_compat.js"
out="addons/web/static/lib/popper_compat/popper_compat.esm.js"
esbuild="${ESBUILD:-node_modules/.bin/esbuild}"
command -v "$esbuild" >/dev/null 2>&1 || [ -x "$esbuild" ] || {
    echo "build.sh: no esbuild at '$esbuild' (set \$ESBUILD)" >&2; exit 127; }

banner='/**
 * Self-contained build of @web/libs/popper_compat, for pages that resolve
 * `@popperjs/core` through an import map instead of a bundler.
 *
 * GENERATED -- do not edit. Rebuild with:
 *     addons/web/static/lib/popper_compat/build.sh
 * Its freshness is enforced by:
 *     tooling/vendored/check_vendored_libs.py --drift
 *
 * @license LGPL-3 (this is first-party Odoo code, not a vendored library)
 */'

tmp="$(mktemp)"
"$esbuild" "$src" --bundle --format=esm --target=es2023 --legal-comments=none \
    --alias:@web=./addons/web/static/src --outfile="$tmp" --log-level=warning
printf '%s\n' "$banner" | cat - "$tmp" > "$tmp.banner"
mv "$tmp.banner" "$tmp"

if [ "$1" = "--check" ]; then
    if cmp -s "$tmp" "$out"; then
        rm -f "$tmp"; echo "popper_compat.esm.js is up to date"; exit 0
    fi
    rm -f "$tmp"; echo "popper_compat.esm.js is STALE -- re-run build.sh" >&2; exit 1
fi
mv "$tmp" "$out"
chmod 644 "$out"
echo "wrote $out"
