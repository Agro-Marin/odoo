#!/bin/bash
set -e
d="$1"
[ -d "$d" ] || { echo "usage: $0 <unzipped-release-dir>" >&2; exit 2; }
find "$d" -name "*.map" -delete
rm -f "$d"/build/pdf.sandbox.mjs "$d"/build/pdf.sandbox.js
rm -f "$d"/web/wasm/quickjs-eval.js "$d"/web/wasm/quickjs-eval.wasm
rm -f "$d"/web/compressed.tracemonkey-pldi-09.pdf
rm -rf "$d"/web/standard_fonts
find "$d" -name "*.mjs" | while read -r f; do mv "$f" "${f%.mjs}.js"; done
find "$d" \( -name "*.js" -o -name "*.html" \) -print0 |
  xargs -0 sed -i -E '/^;\/\//! s/\.mjs\b/.js/g; /^\/\/# sourceMappingURL=/d'
