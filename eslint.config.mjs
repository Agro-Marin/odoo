import js from "@eslint/js";
import prettier from "eslint-plugin-prettier/recommended";
import simpleImportSort from "eslint-plugin-simple-import-sort";
import globals from "globals";

// ─────────────────────────────────────────────────────────────────────────────
// Whitelisted modules — only these are linted.
// Add new modules here as they are onboarded to ESLint.
// ─────────────────────────────────────────────────────────────────────────────
const COMMUNITY_MODULES = [
    "addons/web",
    "addons/board",
    "addons/base_import",
    "addons/bus",
    "addons/html_editor",
    "addons/html_builder",
    "addons/website",
    "addons/website_blog",
    "addons/web_tour",
    "addons/base_setup",
    "addons/purchase",
    "addons/spreadsheet",
    "addons/spreadsheet_account",
    "addons/spreadsheet_dashboard",
    "addons/spreadsheet_dashboard_account",
    "addons/spreadsheet_dashboard_hr_expense",
    "addons/spreadsheet_dashboard_pos_hr",
    "addons/spreadsheet_dashboard_sale",
    "addons/spreadsheet_dashboard_event_sale",
    // Mail & dependents
    "addons/calendar",
    "addons/hr",
    "addons/hr_holidays",
    "addons/hr_skills",
    "addons/im_livechat",
    "addons/mail",
    "addons/portal",
    "addons/snailmail",
    "addons/test_discuss_full",
    "addons/test_mail",
    "addons/website_livechat",
    "addons/website_slides",
    // POS
    "addons/point_of_sale",
    "addons/iot_drivers",
    "addons/l10n_ar_pos",
    "addons/l10n_co_pos",
    "addons/l10n_es_pos",
    "addons/l10n_fr_pos_cert",
    "addons/l10n_gcc_pos",
    "addons/l10n_in_pos",
    "addons/l10n_sa_pos",
    "addons/pos_adyen",
    "addons/pos_discount",
    "addons/pos_epson_printer",
    "addons/pos_hr",
    "addons/pos_hr_restaurant",
    "addons/pos_loyalty",
    "addons/pos_mrp",
    "addons/pos_online_payment",
    "addons/pos_online_payment_self_order",
    "addons/pos_restaurant",
    "addons/pos_restaurant_adyen",
    "addons/pos_restaurant_stripe",
    "addons/pos_sale",
    "addons/pos_sale_loyalty",
    "addons/pos_sale_margin",
    "addons/pos_self_order",
    "addons/pos_self_order_adyen",
    "addons/pos_self_order_epson_printer",
    "addons/pos_self_order_sale",
    "addons/pos_self_order_stripe",
    "addons/pos_stripe",
    // Misc
    "addons/l10n_br_website_sale",
];

const ENTERPRISE_MODULES = [
    "web_enterprise",
    "web_mobile",
    "web_studio",
    "web_cohort",
    "web_gantt",
    "web_grid",
    "web_map",
    "timesheet_grid",
    "timer",
    "industry_fsm",
    "helpdesk",
    "helpdesk_timesheet",
    "helpdesk_sale_timesheet",
    "planning",
    "project_enterprise",
    "documents",
    "documents_spreadsheet",
    "spreadsheet_edition",
    "spreadsheet_dashboard_crm",
    "spreadsheet_dashboard_edition",
    "spreadsheet_dashboard_documents",
    "spreadsheet_sale_management",
    "approvals",
    "test_discuss_full_enterprise",
    "test_mail_enterprise",
    "whatsapp",
    "voip",
    "stock_barcode",
    "stock_barcode_barcodelookup",
    "stock_barcode_mrp",
    "stock_barcode_mrp_subcontracting",
    "stock_barcode_picking_batch",
    "stock_barcode_product_expiry",
    "stock_barcode_quality_control",
    "stock_barcode_quality_control_picking_batch",
    "stock_barcode_quality_mrp",
    "sign",
    "sign_itsme",
    "mrp_workorder",
    "ai",
    "ai_livechat",
    "ai_website_livechat",
    // Enterprise POS
    "l10n_cl_edi_pos",
    "l10n_de_pos_cert",
    "l10n_de_pos_res_cert",
    "l10n_in_reports_gstr_pos",
    "l10n_mx_edi_pos",
    "l10n_pl_reports_pos_jpk",
    "l10n_br_edi_pos",
    "l10n_se_pos",
    "pos_account_reports",
    "pos_blackbox_be",
    "pos_enterprise",
    "pos_hr_mobile",
    "pos_iot",
    "pos_iot_six",
    "pos_online_payment_self_order_preparation_display",
    "pos_order_tracking_display",
    "pos_restaurant_appointment",
    "pos_restaurant_preparation_display",
    "pos_sale_stock_renting",
    "pos_self_order_preparation_display",
    "pos_settle_due",
    "pos_tyro",
];

// Build file globs: "addons/web/**/*.js" etc.
const allModuleGlobs = [...COMMUNITY_MODULES, ...ENTERPRISE_MODULES]
    .map((m) => `${m}/**/*.js`);


/** @type {import("eslint").Linter.Config[]} */
export default [
    // =========================================================================
    // Global ignores — blacklisted paths within whitelisted modules
    // =========================================================================
    {
        ignores: [
            // Vendored third-party libraries (not our code) live under
            // <module>/static/lib/ and are ignored wholesale — by convention,
            // vendored code goes in static/lib and nowhere else, so it is
            // excluded structurally rather than via a per-library allowlist
            // (which always drifts). Putting a third-party file anywhere else is
            // the bug; fix it by relocating into static/lib, not by listing it.
            "**/static/lib/**",
            // hoot is first-party despite living under web/static/lib (historical).
            "!addons/web/static/lib/hoot/**",
            // Vendored bundle that predates the convention. TODO: relocate under
            // static/lib so this special case can go away too.
            "addons/spreadsheet/static/src/o_spreadsheet/o_spreadsheet.js",

            // Legacy code (only top-level adapters are linted)
            "addons/web/static/src/legacy/**",
            "!addons/web/static/src/legacy/*.js",
            "web_enterprise/static/src/legacy/**",
            "!web_enterprise/static/src/legacy/*.js",
            "web_studio/static/src/legacy/**",
            "!web_studio/static/src/legacy/*.js",
            "web_cohort/static/src/legacy/**",
            "web_gantt/static/src/legacy/**",
            "web_map/static/src/legacy/**",
            "addons/base_import/static/src/legacy/**",

            // Legacy tests
            "addons/web/static/tests/**/legacy/*",
            "web_enterprise/static/tests/**/legacy/*",
            "web_studio/static/tests/**/legacy/*",
            "web_cohort/static/tests/legacy/**",
            "web_gantt/static/tests/legacy/**",
            "web_map/static/tests/legacy/**",
        ],
    },

    // =========================================================================
    // Base configuration (eslint:recommended + prettier)
    // =========================================================================
    js.configs.recommended,
    prettier,

    // =========================================================================
    // Main rules — applied to all whitelisted modules
    // =========================================================================
    {
        files: allModuleGlobs,
        plugins: {
            "simple-import-sort": simpleImportSort,
        },
        languageOptions: {
            ecmaVersion: "latest",
            sourceType: "module",
            globals: {
                ...globals.browser,
                // Odoo-specific globals
                odoo: "readonly",
                $: "readonly",
                jQuery: "readonly",
                Chart: "readonly",
                fuzzy: "readonly",
                StackTrace: "readonly",
                QUnit: "readonly",
                luxon: "readonly",
                py: "readonly",
                FullCalendar: "readonly",
                globalThis: "readonly",
                ScrollSpy: "readonly",
                module: "readonly",
                // Test frameworks
                chai: "readonly",
                describe: "readonly",
                it: "readonly",
                mocha: "readonly",
                // Libraries
                DOMPurify: "readonly",
                Prism: "readonly",
                // Bootstrap components
                Alert: "readonly",
                Collapse: "readonly",
                Dropdown: "readonly",
                Modal: "readonly",
                Offcanvas: "readonly",
                Popover: "readonly",
                Tooltip: "readonly",
            },
        },
        rules: {
            "prettier/prettier": ["error", {
                tabWidth: 4,
                semi: true,
                singleQuote: false,
                printWidth: 88,
                endOfLine: "auto",
            }],
            "no-undef": "error",
            "no-restricted-globals": ["error", "event", "self"],
            "no-const-assign": "error",
            "no-debugger": "error",
            "no-dupe-class-members": "error",
            "no-dupe-keys": "error",
            "no-dupe-args": "error",
            "no-dupe-else-if": "error",
            "no-unsafe-negation": "error",
            "no-duplicate-imports": "off",
            "simple-import-sort/imports": ["error", {
                groups: [
                    // Side effect imports
                    ["^\\u0000"],
                    // @odoo, @web, @mail, @point_of_sale, etc.
                    ["^@\\w"],
                    // Relative imports
                    ["^\\."],
                ],
            }],
            "simple-import-sort/exports": "error",
            "valid-typeof": "error",
            "no-unused-vars": ["error", {
                vars: "all",
                args: "none",
                ignoreRestSiblings: false,
                caughtErrors: "all",
            }],
            curly: ["error", "all"],
            "no-restricted-syntax": [
                "error",
                "PrivateIdentifier",
                {
                    // H-5 Pattern 4 smell detector — state-management
                    // review 2026-04-19.  A setter inside a
                    // ``reactive({...})`` literal conflates state with
                    // effects: the setter runs SIDE effects on other
                    // reactive state when ``obj.foo = x`` is written,
                    // hiding a data-flow edge the signal system can't
                    // reason about.  Express the effect explicitly with
                    // ``useEffect(() => ..., () => [obj.foo])`` and
                    // keep the signal itself a plain field.
                    //
                    // The escape hatch — read-only caching / pure
                    // derivation — only needs a getter (no setter), so
                    // this selector only fires on ``set``.
                    selector:
                        "CallExpression[callee.name='reactive'] > ObjectExpression > Property[kind='set']",
                    message:
                        "Pattern 4 smell: setters inside reactive({...}) conflate state with effects. Use plain reactive({foo: null}) + useEffect for side effects, or a SignalStore subclass for computation. See machine_doc_v1/STATE_MANAGEMENT.md §Pattern 4.",
                },
            ],
            "prefer-const": ["error", {
                destructuring: "all",
                ignoreReadBeforeAssign: true,
            }],
            "arrow-body-style": ["error", "as-needed"],
        },
    },

    // =========================================================================
    // Test files (Hoot environment) — all modules, whitelisted or not
    //
    // Hoot's primitives (test/expect/describe…) are IMPORTED from "@odoo/hoot",
    // so they never need to be globals. What test files in NON-whitelisted
    // modules were missing is the base browser environment: they are linted by
    // `js.configs.recommended` (which has no `files` key, so it applies
    // repo-wide) but only whitelisted modules got `globals.browser` above —
    // every `no-undef` hit in static/tests was a browser global (document,
    // window, console, Event, …) or `odoo`. Declare them here for every
    // module's test tree; for whitelisted modules this merges harmlessly with
    // the main block.
    // =========================================================================
    {
        files: ["**/static/tests/**/*.js"],
        languageOptions: {
            globals: {
                ...globals.browser,
                odoo: "readonly",
                luxon: "readonly",
                QUnit: "readonly",
            },
        },
        rules: {
            // Under native ESM, module identity is keyed by resolved URL, so a
            // relative `../src/...` import and the canonical `@addon/...` bare
            // specifier for the same file resolve to TWO distinct module
            // instances. Tests that imported source that way got duplicate
            // class references, breaking `instanceof`/`Array.includes` identity
            // checks (e.g. plugin-set membership) and silently 404'ing on the
            // un-normalized path. Always import addon source via its bare
            // specifier. The old odoo.define loader hid this by normalizing
            // paths; native ESM does not.
            "no-restricted-imports": ["error", {
                patterns: [
                    {
                        group: ["**/../src/**", "**/src/*"],
                        message:
                            "Do not import addon source from a test via a relative '../src/...' path — under native ESM it resolves to a DUPLICATE module instance (breaks class identity / plugin-set membership and 404s the un-normalized URL). Use the canonical bare specifier, e.g. `@html_editor/...` or `@web/...`.",
                    },
                ],
            }],
        },
    },

    // =========================================================================
    // Service Worker override — `self` is the standard global
    // =========================================================================
    {
        files: ["**/service_worker.js"],
        rules: {
            "no-restricted-globals": ["error", "event"],
        },
    },

    // =========================================================================
    // Node tooling scripts — build/typecheck helpers, not browser code
    //
    // Files under a module's tooling/scripts/ (e.g. web/tooling/scripts/
    // typecheck_gate.mjs) run under Node, so they legitimately use `process`,
    // `console`, etc. They are matched by `js.configs.recommended` (no `files`
    // key → repo-wide, and eslint lints .mjs by default) but were never given
    // the main block's browser globals — which is correct, they aren't browser
    // code; they just also lacked Node's. Declare the Node environment for them
    // so their `process`/`console` use stops tripping `no-undef`.
    // =========================================================================
    {
        files: ["**/tooling/scripts/**/*.{js,mjs,cjs}"],
        languageOptions: {
            globals: {
                ...globals.node,
            },
        },
    },

    // =========================================================================
    // Layer boundary enforcement (Feature-Sliced Design)
    //
    // Import direction is law — lower layers cannot import higher.
    // =========================================================================

    // ── Entity layer: model/ ─────────────────────────────────────────────
    {
        files: ["**/web/static/src/model/**/*.js"],
        rules: {
            "no-restricted-imports": ["error", {
                patterns: [
                    {
                        group: ["@web/views/*", "@web/search/*"],
                        message: "Entity layer cannot import widget layer. Use dependency injection.",
                    },
                    {
                        group: ["@web/webclient/*"],
                        message: "Entity layer cannot import page layer.",
                    },
                ],
            }],
        },
    },
    // ── Entity layer: core/domain.js ─────────────────────────────────────
    {
        files: ["**/web/static/src/core/domain.js"],
        rules: {
            "no-restricted-imports": ["error", {
                patterns: [
                    {
                        group: ["@web/views/*", "@web/search/*"],
                        message: "Entity layer cannot import widget layer. Use dependency injection.",
                    },
                    {
                        group: ["@web/webclient/*"],
                        message: "Entity layer cannot import page layer.",
                    },
                ],
            }],
        },
    },
    // ── Feature layer: fields/ ───────────────────────────────────────────
    {
        files: ["**/web/static/src/fields/**/*.js"],
        rules: {
            "no-restricted-imports": ["error", {
                patterns: [
                    {
                        group: ["@web/views/*"],
                        message: "Feature layer (fields/) cannot import widget layer (views/). Move shared code to core/ or use registry indirection.",
                    },
                    {
                        group: ["@web/search/*"],
                        message: "Feature layer (fields/) cannot import widget layer (search/).",
                    },
                    {
                        group: ["@web/webclient/*"],
                        message: "Feature layer cannot import page layer.",
                    },
                ],
            }],
        },
    },
    // ── Shared layer: core/ ──────────────────────────────────────────────
    {
        files: ["**/web/static/src/core/**/*.js"],
        rules: {
            "no-restricted-imports": ["error", {
                patterns: [
                    {
                        group: ["@web/views/*", "@web/search/*"],
                        message: "Shared layer cannot import widget layer.",
                    },
                    {
                        group: ["@web/webclient/*"],
                        message: "Shared layer cannot import page layer.",
                    },
                    {
                        group: ["@web/fields/*"],
                        message: "Shared layer cannot import feature layer.",
                    },
                ],
            }],
        },
    },
    // ── Shared layer: services/ ──────────────────────────────────────────
    {
        files: ["**/web/static/src/services/**/*.js"],
        rules: {
            "no-restricted-imports": ["error", {
                patterns: [
                    {
                        group: ["@web/views/*", "@web/search/*"],
                        message: "Shared layer cannot import widget layer.",
                    },
                    {
                        group: ["@web/webclient/*"],
                        message: "Shared layer cannot import page layer.",
                    },
                    {
                        group: ["@web/fields/*"],
                        message: "Shared layer cannot import feature layer.",
                    },
                ],
            }],
        },
    },
    // ── Shared layer: ui/ ─────────────────────────────────────────────────
    {
        files: ["**/web/static/src/ui/**/*.js"],
        rules: {
            "no-restricted-imports": ["error", {
                patterns: [
                    {
                        group: ["@web/views/*", "@web/search/*"],
                        message: "Shared layer (ui/) cannot import widget layer.",
                    },
                    {
                        group: ["@web/webclient/*"],
                        message: "Shared layer (ui/) cannot import page layer.",
                    },
                    {
                        group: ["@web/fields/*"],
                        message: "Shared layer (ui/) cannot import feature layer.",
                    },
                ],
            }],
        },
    },
    // ── Shared layer: components/ ─────────────────────────────────────────
    {
        files: ["**/web/static/src/components/**/*.js"],
        rules: {
            "no-restricted-imports": ["error", {
                patterns: [
                    {
                        group: ["@web/views/*", "@web/search/*"],
                        message: "Shared layer (components/) cannot import widget layer.",
                    },
                    {
                        group: ["@web/webclient/*"],
                        message: "Shared layer (components/) cannot import page layer.",
                    },
                    {
                        group: ["@web/fields/*"],
                        message: "Shared layer (components/) cannot import feature layer.",
                    },
                ],
            }],
        },
    },

    // =========================================================================
    // Component-lifecycle: ban this.env.services.X in web's component layer
    //
    // ``this.env.services.X`` bypasses the lifecycle-protection wrapper that
    // ``useService("X")`` installs around every method via ``_protectMethod``
    // (core/utils/hooks.js).  Without it, an in-flight promise that resolves
    // after the component unmounts will run on a destroyed component, causing
    // "this.render is not a function" or stale-state bugs that are hard to
    // reproduce.
    //
    // Bare ``env.services.X`` (no ``this``) inside registry factories and
    // command providers is intentionally NOT flagged — those are not OWL
    // components.
    //
    // Scope: web's source files only.  Other addons (POS, mail, hr_attendance)
    // have many existing call sites that need a per-module audit before this
    // rule can be widened safely.
    // =========================================================================
    {
        files: ["**/web/static/src/**/*.js"],
        rules: {
            "no-restricted-syntax": [
                "error",
                "PrivateIdentifier",
                {
                    selector:
                        "CallExpression[callee.name='reactive'] > ObjectExpression > Property[kind='set']",
                    message:
                        "Pattern 4 smell: setters inside reactive({...}) conflate state with effects. Use plain reactive({foo: null}) + useEffect for side effects, or a SignalStore subclass for computation. See machine_doc_v1/STATE_MANAGEMENT.md §Pattern 4.",
                },
                {
                    selector:
                        "MemberExpression[property.name='services'][object.type='MemberExpression'][object.property.name='env'][object.object.type='ThisExpression']",
                    message:
                        "Use useService('X') instead of this.env.services.X. useService adds component-lifecycle protection that prevents promise-resolution-after-destroy bugs. If you genuinely need the raw service (e.g., the dialog outlives the widget), add `// eslint-disable-next-line no-restricted-syntax` with a comment explaining why.",
                },
                // (Removed 2026-05-09) The `Reactive` BC alias was dropped
                // from `@web/core/utils/reactive` along with this rule.
                // Attempting `import { Reactive } from "@web/core/utils/reactive"`
                // now fails at module-load with a native "no such export"
                // error — clearer than a lint warning, and impossible to
                // suppress with eslint-disable.
            ],
        },
    },
];
