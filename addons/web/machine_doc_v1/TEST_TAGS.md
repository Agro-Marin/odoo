# Web Module Test Tags

Quick reference for running targeted subsets of `core/addons/web/tests/`.

## By Speed/Type

| Tag | Type | Tests | Time |
|-----|------|-------|------|
| `web_unit` | TransactionCase (pure Python, + 1 stray HttpCase) | 286 tests | ~45s |
| `web_http` | HttpCase (url_open, no browser) | 87 tests | ~5 min |
| `web_tour` | HttpCase (start_tour/browser_js) | 5 tests | ~2 min |
| `web_js` | Full JS suites (HOOT) | 37 tests | ~1-2 hr |
| `web_perf` | Query count regression (@warmup) | 26 tests | ~2 min |
| `web_benchmark` | Statistical timing (run_benchmark) | 8 tests | ~5 min |
| `click_all` | Click-everywhere (-standard) | 2 tests (TestMenusAdmin, TestMenusDemo) | ~1+ hr |

> Counting basis: these are **tests as Odoo's loader collects them**
> (`odoo.tests.loader.make_suite(['web'], '<tag>')`), which includes methods
> inherited from untagged base classes. That is deliberately *not* a textual
> count of `def test_` inside `@tagged` classes — grepping undercounts
> `web_unit` by 54 and `web_http` by 6, which is how both numbers were wrong
> for months. To reproduce a *run*: `odoo-bin -d <db> --test-enable
> --test-tags <tag> --stop-after-init` and read `odoo.tests.result: … of N
> tests`. Give the HttpCase tags (`web_http`, `web_js`, `click_all`) a real
> port — under `--no-http` they collect 0.
>
> `web_unit` runs 284, not 286, under `--no-http`: `TestJsonExportRoute`
> (`tests/test_json_export.py`) is an **`HttpCase` tagged `web_unit`** rather
> than `web_http`, so its 2 tests disappear silently without a port. That tag
> is inconsistent with this table's own definition of `web_unit`.

> Note: three test files currently carry no `web_*` topic tag — two have
> no `@tagged` at all (`test_esm_pipeline.py`, `test_res_config_settings.py`),
> and one (`test_res_config_doc_links.py`) is tagged only with framework
> conventions (`-standard`, `external`, `post_install`, `-at_install`).
> They are not selected by any of the filters in this table; run with
> the `/web` module filter alone (`-u web`) to include them.

## Granular JS Tests (web_js)

`WebSuite` (desktop) and `MobileWebSuite` (mobile) each have granular test methods
that target specific hoot suite groups via `&id=HASH` URL filters. Use `--test-tags`
to run individual groups instead of the full 1-2 hour suite.

The two classes are not redundant: tests are selected by **tag**, not by
directory, so each platform runs a different (overlapping, neither-a-superset)
set. A change is only verified once both have run. The warm-server dev loop has
the same split behind `hoot --preset desktop|mobile`, where the default hides a
mobile-only suite as a silent zero — see `web/tooling/scripts/README.md`.

| Method | Hoot suite(s) | Scope |
|--------|---------------|-------|
| `test_core` | `@web/core` | utils, registries, RPC, ORM, domain |
| `test_components` | `@web/components` | reusable OWL components (dropdown, pickers, etc.) |
| `test_services` | `@web/services` | orm, hotkey, field, file_upload, debug, etc. |
| `test_ui` | `@web/ui` | overlay services: dialog, popover, tooltip, notification |
| `test_calendar` | `@web/views/calendar` | calendar view |
| `test_fields` | `@web/views/fields` | field widgets (suite path from `tests/views/fields/`, source at `@web/fields/`) |
| `test_form` | `@web/views/form` | form view |
| `test_kanban` | `@web/views/kanban` | kanban view |
| `test_list` | `@web/views/list` | list view |
| `test_graph_pivot` | `@web/views/graph`, `@web/views/pivot_view`, `@web/views/view_components`, `@web/views/view_dialogs`, `@web/views/widgets`, `@web/views/layout`, `@web/views/view_button_hook`, `@web/views/view_service`, `@web/views/view`, `@web/views/view_utils` | graph, pivot, misc view utilities |
| `test_search` | `@web/search` | search bar, filters, groupby |
| `test_webclient` | `@web/webclient` | action manager, navbar, settings |
| `test_public` | `@web/public` | public page components |
| `test_html_editor` | `@html_editor` | rich text editor |
| `test_model` | `@web/model` | client-side relational data model (Record, StaticList, DynamicList, etc.) |
| `test_misc` | `@web/env`, `@web/reactivity`, `@web/t_custom_click` | root-level test files |

```bash
# Single group — desktop only (~30s-2min)
--test-tags '/web:WebSuite.test_calendar' -u web

# Single group — mobile only
--test-tags '/web:MobileWebSuite.test_calendar' -u web

# Multiple groups — both platforms
--test-tags '/web:WebSuite.test_calendar,/web:WebSuite.test_form,/web:MobileWebSuite.test_calendar' -u web

# html_editor desktop
--test-tags '/web:WebSuite.test_html_editor' -u web

# Full suite (existing behavior)
--test-tags 'web_js/web' -u web
```

## By Topic

| Tag | Files | Scope |
|-----|-------|-------|
| `web_action` | test_action | Breadcrumb loading |
| `web_assets` | test_assets | Bundle generation, asset cursors |
| `web_db` | test_db_manager | Database manager UI |
| `web_domain` | test_domain | Domain validation endpoint |
| `web_favorite` | test_favorite | Favorite management tour |
| `web_health` | test_health | /web/health endpoint |
| `web_image` | test_image | Image serving, resize, access tokens |
| `web_layout` | test_base_document_layout | Document layout colors/logo |
| `web_login` | test_login | Login flow, user switching |
| `web_manifest` | test_webmanifest | PWA manifest routes |
| `web_menu` | test_load_menus, test_perf_load_menu | Menu loading + perf |
| `web_model` | test_ir_model | Model access, field creation |
| `web_partner` | test_partner | Partner access, vCard export |
| `web_pivot` | test_pivot_export | Pivot XLSX export |
| `web_profiler` | test_profiler | Profiling enable/disable |
| `web_properties` | test_res_partner_properties | Properties base definition |
| `web_qweb` | test_ir_qweb | QWeb image field rendering |
| `web_redirect` | test_web_redirect | URL redirect handling |
| `web_report` | test_reports | PDF report session/cookies |
| `web_router` | test_router | Action routing/resolution |
| `web_search` | test_web_search_read | web_search_read, web_name_search |
| `web_session` | test_session_info | Session info endpoint perf |
| `web_translate` | test_translate | Translation overrides |
| `web_users` | test_res_users, test_res_users_settings | User settings, name_search |
| `web_controllers_audit` | test_controllers_audit | Controller conventions: docstrings, auth, readonly, methods |
| `web_read_group` | test_web_read_group | `web_read_group` API correctness |
| `web_read` | test_web_read, test_web_read_group, test_search_panel_version, test_web_benchmark, test_web_perf_regression | `web_read` family correctness + perf (cross-cutting tag) |
| `web_save` | test_web_save, test_web_benchmark, test_web_perf_regression | `web_save` correctness (incl. `known_values` field-scoped concurrency) + perf |
| `web_onchange` | test_onchange | Form onchange simulation |
| `web_search_panel` | test_search_panel_version, test_web_benchmark | Search panel endpoints + `__version` stamps |
| `web_cwv` | test_web_cwv_metric | Core Web Vitals beacon model, clamping, retention cron |
| `web_feature_flags` | test_feature_flags | Feature flag resolution cascade |
| `web_typed_services` | test_typed_services_consistency | `@types/registries/services.d.ts` ↔ runtime registry consistency |
| `assets_bundle` | test_assets | Bundle generation timings and asset cursors (sub-tag alongside `web_assets`) |
| `web_bundle_size` | test_web_bundle_size | ESM bundle byte-size regression gate; pins upper-bound budgets per bundle (sub-tag alongside `web_perf` and `web_assets`) |

## HOOT suite scoping (`&module_scope=`)

`web.assets_unit_tests_setup` pulls in `web.assets_backend`, so an unscoped
`/web/tests` page executes the `src` of **every installed addon**. Those side
effects are global and unconditional (registry entries, `patch()` calls), while
mock models are opt-in per suite via `defineModels()`. The asymmetry meant one
addon's `src` routinely reached for a model another addon's suite never
defined, and the mock server could only answer *"Cannot find a definition for
model X"* — e.g. `mail`'s chatter patches made `@web/webclient`'s
`res_user_group_ids_field` suite fail on `mail.thread`, and enterprise `ai`'s
command provider logged `ai.agent unavailable` throughout `@mail`'s suites.

`_run_hoot` now appends `&module_scope=<addon>`, derived from the `@<addon>`
prefix its suite names already carry. `ir.asset._get_active_addons_list`
(`web/models/ir_asset.py`) narrows every bundle on that request to the addon's
**manifest dependency closure** — for `mail` that is `{mail, web_tour,
html_editor, bus, web, base}`. What cannot load cannot register.

- **Inert without the param.** No `module_scope` → `_get_asset_params()` is
  unchanged → the ormcache key, the bundle and today's behaviour are identical.
  Only honoured on `/web/tests*`, so a stray param cannot fragment the asset
  cache of ordinary pages.
- **No URL collision.** A bundle's `unique` is a SHA256 over its asset
  descriptors (`assetsbundle/bundle.py::get_checksum`) and ESM artifacts are
  content-addressed, so a scoped bundle mints its own URL and can never
  overwrite the unscoped attachment. No `_get_asset_bundle_url` override is
  needed (unlike `website`, whose custom-SCSS URLs *can* collide).
- **Suites get stricter.** A suite that passed only because a foreign addon's
  `src` happened to be loaded will now fail. That is the point; treat such a
  failure as a real missing dependency, not as scoping breakage.
- `hoot_filters` (an explicit `--test-tags` path) suppresses scoping: the path
  may select suites from another addon.
- `im_livechat`'s `/web/tests/livechat` external suite passes no scope and
  stays unscoped by design — it is deliberately cross-addon.

Covered by `tests/test_ir_asset_scope.py` (tag `asset_scope`).

## JS Legacy QUnit chain — REMOVED

The legacy QUnit test chain has been fully removed from this fork. All JS unit
testing now runs through **HOOT** (`web.assets_unit_tests*` bundles, driven by
`/web/tests` and `test_js.py`'s `_run_hoot`).

What was deleted:

- `static/tests/legacy/` (the whole 28-file, ~9,081 LOC tree: 6 QUnit suites +
  ~22 helper/glue files)
- Vendored `static/lib/qunit/` (QUnit 2.9.1, css + 6,612 LOC js, ~200 KB)
- Bundles `web.tests_assets`, `web.__assets_tests_call__`,
  `web.qunit_suite_tests` (in `web/__manifest__.py`) and the per-consumer
  contributions to them (calendar, hr, hr_calendar, hr_attendance, mail,
  barcodes, l10n_ro_edi, website, im_livechat `qunit_embed_suite`;
  enterprise: web_enterprise, web_map, web_studio, web_grid, pos_settle_due
  `point_of_sale.assets_qunit_tests`)
- Controller route `/web/tests/legacy` and templates `web.qunit_suite` /
  `web.test_helpers` (`web/controllers/webclient.py`,
  `web/views/webclient_templates.xml`)
- `web.qunit_suite_tests.js` entry in the `test_assets.py` bundle-timing budget

Disposition of the 6 former QUnit suites:

| Former suite | Disposition |
|---|---|
| `legacy_tests/core/class_tests.js` | **Ported** → `tests/legacy_js/class.test.js`, then **deleted 2026-07-23** with the retired `Class` system |
| `public/public_widget_tests.js` | **Ported** → `tests/legacy_js/public_widget.test.js`, then **deleted 2026-07-23** with the retired `publicWidget` (lazyloader suite moved to `tests/public/`) |
| `core/utils/nested_sortable_tests.js` | Deleted — helper-only file (no `QUnit.test`); HOOT coverage in `tests/core/utils/nested_sortable.test.js` |
| `views/graph_view_tests.js` | Deleted — helper-only file (no `QUnit.test`); HOOT coverage in `tests/views/graph/graph_view.test.js` |
| `legacy_tests/helpers/test_utils_tests.js` | Deleted — meta-test of the deleted legacy `patchDate` helper (obsolete under HOOT's mock clock) |
| `mock_server_tests.js` | Deleted — tested the legacy `MockServer`; superseded by HOOT's server-model mocking framework |

## Examples

```bash
# Fast feedback (~30s)
--test-tags='web_unit/web' -u web

# Single topic
--test-tags='web_image' -u web

# Multiple topics
--test-tags='web_image,web_login' -u web

# All HTTP tests (~5 min)
--test-tags='web_http/web' -u web

# Everything except slow JS/tours
--test-tags='/web,-web_js,-web_tour,-click_all'

# Only perf regression
--test-tags='web_perf' -u web

# Full suite (nightly)
--test-tags='*/web' -u web
```
