#!/bin/bash
# Reshape an upstream pdf.js prebuilt release ("pdfjs-<v>-dist.zip" from the
# GitHub releases page -- the npm package ships no full viewer) into the layout
# vendored here. Run this BEFORE applying agromarin-fork.patch.
#
#   ./mechanise.sh <unzipped-release-dir>
#
#  - ESM files carry .js, not .mjs, and every intra-tree reference follows.
#  - Source maps are not shipped, so their references are stripped rather than
#    rewritten: a rewritten-but-absent .map 404s in devtools.
#  - The scripting sandbox (pdf.sandbox.*) and its QuickJS engine
#    (web/wasm/quickjs-eval.*, ~475 kB) are dropped: this fork sets
#    enableScripting=false, so nothing loads them.
#  - The sample PDF and the standard-font pack are not shipped either.
#  - web/wasm/{openjpeg,jbig2,qcms}* ARE kept: since v6 those codecs live
#    outside the worker bundle and pdf.js fetches them at runtime.
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
  xargs -0 sed -i -E 's/\.mjs\b/.js/g; /^\/\/# sourceMappingURL=/d'
