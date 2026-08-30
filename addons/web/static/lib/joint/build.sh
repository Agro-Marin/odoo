#!/usr/bin/env bash

set -euo pipefail

cd "$(dirname "$0")"

JOINT_VERSION="${1:-4.3.2}"
LAYOUT_VERSION="${2:-4.3.0}"
ESBUILD_VERSION="0.25.0"

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

cp entry.js "$workdir/"
cd "$workdir"
npm install --silent --no-package-lock \
    "@joint/core@${JOINT_VERSION}" \
    "@joint/layout-directed-graph@${LAYOUT_VERSION}"

npx "esbuild@${ESBUILD_VERSION}" entry.js \
    --bundle \
    --format=esm \
    --target=es2023 \
    --minify \
    --legal-comments=inline \
    --banner:js="/*! JointJS ${JOINT_VERSION} | MPL-2.0 | https://www.jointjs.com
 * Bundled with @joint/layout-directed-graph ${LAYOUT_VERSION} (MPL-2.0), which
 * carries @dagrejs/dagre and @dagrejs/graphlib (MIT). See build.sh and the
 * LICENSE files in this directory.
 * Not a pristine upstream file. */" \
    --outfile=joint.esm.js

cd - >/dev/null
cp "$workdir/joint.esm.js" .
cp "$workdir/node_modules/@joint/core/LICENSE" LICENSE
cp "$workdir/node_modules/@dagrejs/dagre/LICENSE" LICENSE.dagre
cp "$workdir/node_modules/@dagrejs/graphlib/LICENSE" LICENSE.graphlib

echo "Rebuilt joint.esm.js at ${JOINT_VERSION} ($(stat -c%s joint.esm.js) bytes)."
echo "Update ../versions.json in the same commit."
