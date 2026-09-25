#!/usr/bin/env bash
# The ESM gates of test_lint on a narrow install (core addons only), in a
# scratch database created and dropped here, so CI can run them unattended.
#
#   odoo/addons/test_lint/lint_esm_gates.sh                  run the ESM gates
#   odoo/addons/test_lint/lint_esm_gates.sh --keep           keep the database
#   odoo/addons/test_lint/lint_esm_gates.sh --http-port <n>  the tests' HTTP port (default 8279)
#
# The narrow install judges only what it installs: the bundle
# checks see test_lint's closure, while the specifier and orphan scans read
# every addon on the path. lint_full_scope.sh is the production-scope run.
set -u

usage() { sed -n '2,11p' "$0"; exit 2; }

ESM_GATES=(
    TestAssetPathsExist TestBundleDoubleEvaluation TestBundlesAssemble
    TestEsmBundles TestEsmSpecifiers TestOrphanAssets
    TestOrphanTestRegistrations TestSetupBundleHasNoTests
)

KEEP=0 PORT=8279
while [ $# -gt 0 ]; do
    case "$1" in
        --keep) KEEP=1 ;;
        --http-port) shift; PORT="${1:-}"; [ -n "$PORT" ] || usage ;;
        -h|--help) usage ;;
        *) echo "unknown option: $1" >&2; usage ;;
    esac
    shift
done

CHECKOUT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PYTHON="${VIRTUAL_ENV:+$VIRTUAL_ENV/bin/}python"
DB="lint_esm_${USER:-ci}_$$"
DATA_DIR="$(mktemp -d "${TMPDIR:-/tmp}/lint_esm.XXXXXX")"

cleanup() {
    if [ "$KEEP" -eq 1 ]; then
        echo "kept database $DB (data dir $DATA_DIR)"
        return
    fi
    dropdb --if-exists "$DB"
    rm -rf "$DATA_DIR"
}
trap cleanup EXIT

TAGS="$(printf '/test_lint:%s,' "${ESM_GATES[@]}")"
createdb "$DB" || exit 1
"$PYTHON" "$CHECKOUT/odoo-bin" \
    --addons-path="$CHECKOUT/odoo/addons,$CHECKOUT/addons" --data-dir="$DATA_DIR" \
    -d "$DB" --db-filter="^$DB\$" -i test_lint --test-enable --test-tags "${TAGS%,}" \
    --stop-after-init --workers=0 --max-cron-threads=0 --http-port "$PORT" \
    --log-level=warn
