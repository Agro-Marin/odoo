# Web Module JS — Full Systematic Performance & Correctness Audit

## Context

Complete re-audit of ALL 609 JS files (~109K lines) in the web module.
Previous PC-01 through PC-04 passes were done with a less capable model — redo everything.
Previous findings (13 bugs) serve as baseline, not as exemptions.

## Audit Protocol Per File

For each JS file, check:

### Correctness (C-xx)
- C-01: Logic errors (wrong condition, wrong branch, off-by-one)
- C-02: Type confusion (string vs number, null vs undefined, array vs object)
- C-03: Null/undefined dereference (missing guards on .find(), .exec(), optional chaining)
- C-04: Stale closures / shared mutable state across instances
- C-05: Wrong API usage (classList.contains with ".", removeEventListener wrong ref, etc.)
- C-06: Missing return / missing await (promises that aren't chained)
- C-07: Race conditions (async sequences without proper serialization)
- C-08: Data corruption (mutations to shared objects, aliased references)
- C-09: Resource leaks (listeners, timers, object URLs not cleaned up)

### Performance (P-xx)
- P-01: O(n²) or worse in hot paths (nested loops over records/fields)
- P-02: Unnecessary DOM reads/writes in loops (layout thrashing)
- P-03: Missing memoization / repeated expensive computation
- P-04: Excessive re-renders (reactive state updates that trigger unnecessary OWL patches)
- P-05: Large object allocation in hot paths (spreading large arrays/objects per iteration)

### Maintenance (M-xx)
- M-01: Dead code (unreachable branches, unused exports, impossible conditions)
- M-02: Misleading names / typos in user-facing or developer-facing strings
- M-03: Inconsistent patterns vs rest of codebase

### Severity
- [P1] — Bug/perf issue affects production users
- [P2] — Bug/perf issue affects edge cases or developer experience
- [P3] — Code quality issue, low risk

## Phase Plan (16 phases, all 609 files)

### Phase 1: core/ root + core/utils/ (49 files, 9,767 lines)
core/ root (9 files, 2,115 lines): domain.js, registry.js, assets.js, events.js,
context.js, template_inheritance.js, templates.js, action_hook.js, constants.js.
core/utils/ (40 files, 7,652 lines): concurrency.js, timing.js, hooks.js, macro.js,
search.js, indexed_db.js, files.js, virtual_grid.js, urls.js, dependency_graph.js,
render.js, reactive.js, patch.js, pdfjs.js, order_by.js, functions.js, decorations.js,
dom/ (scrolling, autoresize, html, xml, ui, events, classname, dvu),
dnd/ (draggable_hook_builder, draggable_hook_builder_utils, draggable_hook_builder_owl,
draggable, sortable, sortable_owl, nested_sortable),
format/ (numbers, strings, colors, binary), collections/ (arrays, objects, cache).

### Phase 2: core/browser/ + core/errors/ + core/colors/ + core/position/ + core/network/ (16 files, 3,018 lines)
core/browser/ (6 files, 834 lines): browser.js, cookie.js, feature_detection.js,
anchor_scroll.js, hotkeys.js, router.js.
core/errors/ (2 files, 263 lines): error_utils.js, uncaught_errors.js.
core/colors/ (1 file, 222 lines): colors.js.
core/position/ (2 files, 515 lines): position_hook.js, utils.js.
core/network/ (5 files, 1,184 lines): rpc.js, rpc_cache.js, rpc_dedup.js,
content_disposition.js, download.js.

### Phase 3: core/l10n/ + core/py_js/ (19 files, 4,178 lines)
core/l10n/ (10 files, 1,605 lines): localization.js, translation.js, time.js,
date_utils.js, date_serialization.js, dates.js, utils.js,
utils/locales.js, utils/normalize.js, utils/format_list.js.
core/py_js/ (9 files, 2,573 lines): py.js, py_builtin.js, py_date.js,
py_date_helpers.js, py_interpreter.js, py_parser.js, py_timedelta.js,
py_tokenizer.js, py_utils.js.

### Phase 4: core/tree/ (16 files, 1,936 lines)
ast_utils.js, condition_tree.js, construct_domain_from_tree.js,
construct_expression_from_tree.js, construct_tree_from_domain.js,
construct_tree_from_expression.js, domain_contains_expressions.js,
domain_from_tree.js, expression_from_tree.js, in_range_options.js,
operator_labels.js, operators.js, tree_from_domain.js,
tree_from_expression.js, utils.js, virtual_operators.js.

### Phase 5: model/ (33 files, 8,745 lines)
model/ root (6 files, 1,673 lines): model.js, record.js, sample_data.js,
sample_field_generators.js, sample_server.js, types.js.
model/relational_model/ (27 files, 7,072 lines): relational_model.js, record.js,
static_list.js, dynamic_list.js, dynamic_group_list.js, dynamic_record_list.js,
group.js, data_point.js, field_context.js, field_metadata.js, field_spec.js,
operation.js, record_preprocessors.js, record_save.js, record_validator.js,
record_value_transforms.js, resequence.js, static_list_command_engine.js,
static_list_sort.js, static_list_utils.js, commands.js, errors.js, utils.js, etc.

### Phase 6: services/ (31 files, 5,419 lines)
All service files: orm_service.js, effect_service.js, notification_service.js,
dialog_service.js, popover_service.js, tooltip_service.js, hotkey_service.js,
title_service.js, profiling_service.js, tree_processor_service.js,
sortable_service.js, install_scoped_app/, debug/ files, etc.

### Phase 7: search/ (31 files, 7,353 lines)
search_model.js, search_state.js, search_query_mutations.js,
search_panel/ (search_panel_state.js, search_panel_fetch.js, search_panel.js),
comparison_menu.js, favorite_menu.js, group_by_menu.js, filter_menu.js,
search_bar.js, search_bar_menu.js, facets.js, with_search.js, etc.

### Phase 8: ui/ (20 files, 2,566 lines) + public/ (11 files, 1,868 lines) + misc (8 files, ~600 lines)
ui/: popover/, tooltip/, autocomplete/, draggable/, etc.
public/: public_component_service.js, etc.
misc: session.js, env.js, module_loader.js, service_worker.js,
boot/ (2 files), polyfills/, libs/.
legacy/ (6 files, 1,976 lines).

### Phase 9: components/ part 1 — larger (35 files, ~6,500 lines)
datetime/ (5, 1,466), color_picker/ (4, 1,267), tree_editor/ (5, 1,120),
dropdown/ (9, 905), barcode/ (4, 661), autocomplete/ (1, 531),
model_field_selector/ (2, 521), select_menu/ (1, 491),
record_selectors/ (5, 474).

### Phase 10: components/ part 2 — smaller (38 files, ~6,000 lines)
file_viewer/ (3, 464), errors/ (2, 459), signature/ (2, 401),
time_picker/ (1, 299), domain_selector/ (3, 281), pager/ (2, 268),
action_swiper/ (1, 240), resizable_panel/ (1, 230), notebook/ (1, 216),
code_editor/ (1, 208), expression_editor/ (2, 182), dropzone/ (2, 139),
file_input/ (1, 125), model_selector/ (1, 121), domain_selector_dialog/ (1, 118),
checkbox/ (1, 104), file_upload/ (3, 100), ir_ui_view_code_editor/ (1, 92),
expression_editor_dialog/ (1, 87), colorlist/ (1, 71), user_switch/ (1, 66),
copy_button/ (1, 55), tags_list/ (1, 51), + root (2, 204).

### Phase 11: fields/ part 1 — relational + specialized (40 files, 7,795 lines)
fields/relational/ (20 files, 3,527 lines): many2one_field.js, many2many_field.js,
many2many_tags_field.js, x2many_field.js, many2one_avatar_field.js, etc.
fields/specialized/ (20 files, 4,268 lines): domain_field.js, properties_field.js,
res_user_group_ids_field.js, color_field.js, statusbar_field.js, etc.

### Phase 12: fields/ part 2 — basic + temporal + media + selection + display + hooks + root (55 files, 7,867 lines)
fields/basic/ (24, 1,745), fields/display/ (9, 989), fields/temporal/ (4, 962),
fields/media/ (7, 902), fields/selection/ (10, 846), fields/hooks/ (1, 68),
fields/ root (15, 2,355).

### Phase 13: views/ part 1 — list + form (32 files, 8,154 lines)
views/list/ (18 files, 5,827 lines): list_renderer.js, list_controller.js,
list_arch_parser.js, list_group_layout.js, etc.
views/form/ (14 files, 2,327 lines): form_controller.js, form_compiler.js,
form_renderer.js, form_arch_parser.js, etc.

### Phase 14: views/ part 2 — kanban + calendar (36 files, 7,600 lines)
views/kanban/ (16 files, 3,678 lines): kanban_renderer.js, kanban_controller.js,
kanban_record.js, kanban_compiler.js, etc.
views/calendar/ (20 files, 3,922 lines): calendar_model.js, calendar_controller.js,
calendar_renderer.js, etc.

### Phase 15: views/ part 3 — pivot + graph + settings + rest (51 files, 10,908 lines)
views/pivot/ (11 files, 2,434 lines): pivot_model.js, pivot_renderer.js, etc.
views/graph/ (7 files, 1,958 lines): graph_renderer.js, graph_model.js, etc.
views/settings/ (21, 1,316), views/view_dialogs/ (3, 803),
views/view_components/ (7, 653), views/widgets/ (8, 573),
views/view_button/ (3, 415), views/ root (12, 2,756).

### Phase 16: webclient/ (45 files, 6,384 lines)
webclient/actions/ (17, 3,035): action_service.js, action_button_executor.js,
action_info_builders.js, action_state.js, action_views.js, breadcrumb_manager.js,
report_executor.js, action_dialog.js, skeleton_view.js, etc.
webclient/debug/ (5, 610), webclient/clickbot/ (2, 601),
webclient/switch_company_menu/ (2, 468), webclient/menus/ (3, 321),
webclient/navbar/ (1, 273), webclient/user_menu/ (2, 240),
+ remaining small dirs + root files.

## Output Format

Each phase produces `phase_audit_NN_output.md` in this directory with:
1. Fixed Findings (severity, category code, file:line, code, problem, fix)
2. Skip Registry (patterns that look wrong but are intentional — with evidence)
3. Files with No Findings
4. Delta vs PC-0x (for Phases 1-5): note which PC findings were confirmed, which were
   missed, and any new findings

## Totals

| Metric | Value |
|--------|-------|
| Total files | ~609 (excl. emoji_data.js) |
| Total lines | ~109K |
| Phases | 16 |
| PC-01 to PC-04 findings (baseline) | 13 bugs |
