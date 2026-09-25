#!/usr/bin/env bash
# test_lint on a fuller install, where the gates that read the registry or the
# served bundles can see the modules they judge.
#
#   odoo/addons/test_lint/lint_full_scope.sh                  install FULL_SCOPE into a scratch DB, run /test_lint, drop it
#   odoo/addons/test_lint/lint_full_scope.sh --keep           keep the database for a re-run
#   odoo/addons/test_lint/lint_full_scope.sh --db <name>      use (or create) that database
#   odoo/addons/test_lint/lint_full_scope.sh --tags <spec>    a narrower --test-tags, e.g. /test_lint:TestFieldDeclarations
#   odoo/addons/test_lint/lint_full_scope.sh --http-port <n>  the tests' HTTP port (default 8269)
set -u

usage() { sed -n '2,10p' "$0"; exit 2; }

FULL_SCOPE=(
    test_lint
    accountant account_edi_ubl_cii account_payment_provider approval_purchase
    asset_ledger_maintenance automation calendar crm document event_sale
    google_address_autocomplete helpdesk hr_expense hr_expense_stripe
    hr_gamification hr_holidays hr_recruitment hr_skills_slides im_livechat mrp
    onboarding point_of_sale pos_sale project purchase sale spreadsheet_dashboard
    stock_account survey website_sale
)

DB="" KEEP=0 TAGS="/test_lint" PORT=8269
while [ $# -gt 0 ]; do
    case "$1" in
        --keep) KEEP=1 ;;
        --db) shift; DB="${1:-}"; [ -n "$DB" ] || usage ;;
        --tags) shift; TAGS="${1:-}"; [ -n "$TAGS" ] || usage ;;
        --http-port) shift; PORT="${1:-}"; [ -n "$PORT" ] || usage ;;
        -h|--help) usage ;;
        *) echo "unknown option: $1" >&2; usage ;;
    esac
    shift
done

CHECKOUT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
if [ -n "${VIRTUAL_ENV:-}" ]; then
    VENV="$VIRTUAL_ENV"
elif [ -x "$CHECKOUT/../p314o19m/bin/python" ]; then
    VENV="$(cd "$CHECKOUT/../p314o19m" && pwd)"
else
    echo "no virtualenv: activate one or create ../p314o19m (CLAUDE.md §5)" >&2
    exit 2
fi
# The full scope is the workspace addons path, so the environment's conf is
# required: without it enterprise and agromarin are not on the path at all.
CONF="$(dirname "$VENV")/$(basename "$VENV").conf"
[ -f "$CONF" ] || { echo "no $CONF: the full scope reads its addons_path" >&2; exit 2; }
DATA_DIR="$(sed -n 's/^data_dir *= *//p' "$CONF")"
# The conf names the workspace checkout's addons; a --ref worktree must grade
# its own, so this checkout's addons replace that entry.
ADDONS_PATH="$(sed -n 's/^addons_path *= *//p' "$CONF" | tr ',' '\n' |
    sed "s#^.*/odoo/addons\$#$CHECKOUT/addons#" | paste -sd,)"
DB="${DB:-lint_full_${USER}_$$}"
LOGS="${TMPDIR:-$HOME/.cache}/lint_full_scope"
mkdir -p "$LOGS"

odoo() {
    "$VENV/bin/python" "$CHECKOUT/odoo-bin" -c "$CONF" --addons-path "$ADDONS_PATH" \
        -d "$DB" --db_maxconn=6 --stop-after-init "$@"
}

missing() {
    psql -U "$USER" -d "$DB" -Atc "SELECT name FROM ir_module_module
        WHERE name = ANY(string_to_array('$(IFS=,; echo "${FULL_SCOPE[*]}")', ','))
        AND state <> 'installed' ORDER BY name"
}

cleanup() {
    [ "$KEEP" -eq 1 ] && { echo "kept database $DB"; return; }
    dropdb -U "$USER" --if-exists "$DB"
    [ -n "$DATA_DIR" ] && rm -rf "$DATA_DIR/filestore/$DB"
}
trap cleanup EXIT

# A single -i converges on a subgraph and exits 0 with modules left
# uninstalled (CLAUDE.md §8): install until the missing set stops shrinking.
todo="$(IFS=,; echo "${FULL_SCOPE[*]}")"
previous=""
for pass in 1 2 3; do
    echo "install pass $pass: $todo"
    odoo -i "$todo" --no-http >"$LOGS/$DB.install$pass.log" 2>&1 || {
        echo "install failed, see $LOGS/$DB.install$pass.log" >&2
        exit 1
    }
    left="$(missing)"
    [ -z "$left" ] && break
    [ "$left" = "$previous" ] && { echo "not installable: $left" >&2; exit 1; }
    previous="$left"
    todo="$(echo "$left" | paste -sd,)"
done
[ -z "$(missing)" ] || { echo "still not installed: $(missing | paste -sd' ')" >&2; exit 1; }

echo "test_lint $TAGS on $DB ($(psql -U "$USER" -d "$DB" -Atc "SELECT count(*) FROM ir_module_module WHERE state = 'installed'") modules installed)"
odoo -u test_lint --test-enable --test-tags "$TAGS" --http-port "$PORT" >"$LOGS/$DB.tests.log" 2>&1
rc=$?
grep -E " (FAIL|ERROR): |tests when loading" "$LOGS/$DB.tests.log" | sed 's/^.* odoo\./odoo./'
echo "log: $LOGS/$DB.tests.log"
exit "$rc"
