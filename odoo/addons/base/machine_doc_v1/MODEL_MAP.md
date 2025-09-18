# Base Module Model Map

Every Python model defined or extended by the `base` module, with fields, key methods, and purpose.

---

## Actions System

### models/ir_actions.py

Defines all action types — the core navigation primitives of the webclient.

#### IrActions — `ir.actions.actions` (`_name`, `_table = ir_actions`)

Base action model. All action types inherit from this.

**Fields:**
- `name` (Char, required, translatable)
- `type` (Char, required) — Action type discriminator
- `xml_id` (Char, computed) — External identifier
- `path` (Char) — URL path (unique constraint)
- `help` (Html, translatable) — Empty list help text
- `binding_model_id` (Many2one → ir.model) — Model to bind action to
- `binding_type` (Selection) — `action` or `report`
- `binding_view_types` (Char, default=`list,form`) — Views where binding appears

**Key Methods:**
- `get_bindings(model_name)` — Retrieve bound actions for a model
- `_for_xml_id(full_xml_id)` — Get action record by XML ID
- `_get_action_dict()` — Return action data dict for webclient
- `_get_readable_fields()` — Fields safe for web access

#### IrActionsAct_Window — `ir.actions.act_window` (`_name`, inherits `ir.actions.actions`)

Window action — opens a view on a model.

**Fields:**
- `view_id` (Many2one → ir.ui.view) — Specific view
- `domain` (Char) — Python expression for filtering
- `context` (Char, required, default=`{}`) — Python dict
- `res_id` (Integer) — Record ID for form view
- `res_model` (Char, required) — Target model
- `target` (Selection) — `current`, `new`, `fullscreen`, `main`
- `view_mode` (Char, required) — Comma-separated: `list,form,kanban,...`
- `mobile_view_mode` (Char, default=`kanban`)
- `view_ids` (One2many → ir.actions.act_window.view)
- `views` (Binary, computed) — Ordered `(view_id, view_mode)` pairs
- `limit` (Integer, default=80) — Records per page
- `group_ids` (Many2many → res.groups) — Group restrictions
- `search_view_id` (Many2one → ir.ui.view) — Search view
- `embedded_action_ids` (One2many, computed) — Embedded actions
- `filter` (Boolean), `cache` (Boolean, default=True)

**Key Methods:**
- `_compute_views()` — Compute ordered view list
- `read(fields, load)` — Enriches help from model's `get_empty_list_help()`
- `_get_action_dict()` — Includes embedded actions data

#### IrActionsAct_WindowView — `ir.actions.act_window.view` (`_name`)

View ordering within a window action.

**Fields:**
- `sequence` (Integer), `view_id` (Many2one → ir.ui.view)
- `view_mode` (Selection, required) — list, form, graph, pivot, calendar, kanban
- `act_window_id` (Many2one → ir.actions.act_window, cascade)
- `multi` (Boolean)

#### IrActionsAct_Window_Close — `ir.actions.act_window_close` (`_name`, inherits actions)

Close window action. Minimal — just inherits type.

#### IrActionsAct_Url — `ir.actions.act_url` (`_name`, inherits actions)

URL action — opens an external URL.

**Fields:**
- `url` (Text, required), `target` (Selection) — `new`, `self`, `download`

#### IrActionsTodo — `ir.actions.todo` (`_name`)

Configuration wizard queue.

**Fields:**
- `action_id` (Many2one → ir.actions.actions, required)
- `sequence` (Integer, default=10), `state` (Selection) — `open`, `done`

**Key Methods:**
- `ensure_one_open_todo()` — Keep only one open todo
- `action_launch()` — Launch wizard action

#### IrActionsClient — `ir.actions.client` (`_name`, inherits actions)

Client-side action — triggers a JS component.

**Fields:**
- `tag` (Char, required) — Client action identifier
- `target` (Selection), `res_model` (Char), `context` (Char)
- `params` (Binary, computed/inverse), `params_store` (Binary)

---

### models/ir_actions_report.py

#### IrActionsReport — `ir.actions.report` (`_name`, inherits actions)

Report actions — renders QWeb templates to PDF/HTML/text via WeasyPrint.

**Fields:**
- `model` (Char, required) — Target model name
- `report_type` (Selection, required) — `qweb-html`, `qweb-pdf`, `qweb-text`
- `report_name` (Char, required) — QWeb template name
- `report_file` (Char) — Path to report file
- `group_ids` (Many2many → res.groups)
- `paperformat_id` (Many2one → report.paperformat)
- `print_report_name` (Char, translatable) — Filename expression
- `attachment_use` (Boolean) — Reload from cached attachment
- `attachment` (Char) — Save prefix expression

**Key Methods:**
- `retrieve_attachment(record)` — Get cached report attachment
- `get_paperformat()` — Get paper format (self or company default)
- `_render_html_to_pdf(bodies, report_ref, landscape, ...)` — WeasyPrint PDF rendering
- `_render_html_to_image(bodies, width, height, ...)` — WeasyPrint PNG rendering
- `_render_qweb_html(docids, data)` — Render QWeb to HTML
- `_render_qweb_pdf(docids, data)` — Render QWeb to PDF
- `_render_qweb_text(docids, data)` — Render QWeb to text
- `report_action(docids, data, config)` — Return action dict for webclient

---

### models/ir_actions_server.py

#### IrActionsServer — `ir.actions.server` (`_name`, inherits actions)

Automated server actions — execute code, CRUD operations, or webhooks.

**Fields:**
- `state` (Selection, required) — `object_write`, `object_create`, `object_copy`, `code`, `webhook`, `multi`
- `usage` (Selection) — `ir_actions_server` or `ir_cron`
- `model_id` (Many2one → ir.model, required)
- `model_name` (Char, related)
- `code` (Text) — Python code to execute
- `child_ids` (One2many → self) — Sub-actions for `multi` state
- `update_path` (Char) — Field path for write operations
- `update_m2m_operation` (Selection) — `add`, `remove`, `set`, `clear`
- `value` (Text) — Expression or literal value
- `evaluation_type` (Selection) — `value`, `sequence`, `equation`
- `webhook_url` (Char), `webhook_field_ids` (Many2many → ir.model.fields)

**Key Methods:**
- `run()` — Main entry point, dispatches to runner
- `_run_action_code_multi(eval_context)` — Execute Python code
- `_run_action_object_write(eval_context)` — Update records
- `_run_action_object_create(eval_context)` — Create record
- `_run_action_object_copy(eval_context)` — Duplicate record
- `_run_action_webhook(eval_context)` — Send POST request
- `_run_action_multi(eval_context)` — Run child actions sequentially
- `_get_eval_context(action)` — Build safe evaluation context
- `create_action()`, `unlink_action()` — Manage action bindings

#### IrActionsServerHistory — `ir.actions.server.history` (`_name`)

Code revision history for server actions.

**Fields:**
- `action_id` (Many2one → ir.actions.server, cascade), `code` (Text)

**Key Methods:**
- `_gc_histories()` — Autovacuum, keeps last 100 entries

#### ServerActionHistoryWizard — `server.action.history.wizard` (TransientModel)

Wizard to view diffs and restore previous code revisions.

---

## Model Registry

### models/ir_model.py

#### IrModel — `ir.model` (`_name`)

Model metadata registry — one record per ORM model.

**Fields:**
- `name` (Char, translatable, required) — Human-readable description
- `model` (Char, required) — Technical model name (e.g., `res.partner`)
- `order` (Char, default=`id`, required) — Default SQL ordering
- `field_id` (One2many → ir.model.fields, required)
- `inherited_model_ids` (Many2many, computed)
- `state` (Selection) — `manual` (Studio) or `base` (code-defined)
- `access_ids` (One2many → ir.model.access), `rule_ids` (One2many → ir.rule)
- `abstract` (Boolean), `transient` (Boolean)
- `modules` (Char, computed) — Installed modules defining this model
- `count` (Integer, computed) — Total records
- `fold_name` (Char) — Field for kanban column folding

**Key Methods:**
- `_get(name)` — Get model record by technical name
- `_get_id(name)` — Get model ID by name (ormcache)
- `_reflect_models(model_names)` — Sync model metadata from registry to DB
- `create(vals_list)` — Create + reload registry
- `write(vals)` — Update + reload if order/fold_name changed
- `unlink()` — Delete + cleanup fields/crons/data + reload registry

#### IrModelInherit — `ir.model.inherit` (`_name`)

Tracks model inheritance relationships.

**Fields:**
- `model_id` (Many2one → ir.model, required)
- `parent_id` (Many2one → ir.model, required)
- `parent_field_id` (Many2one → ir.model.fields) — For `_inherits` only

**Key Methods:**
- `_reflect_inherits(model_names)` — Sync inheritance tree from registry

---

### models/ir_model_fields.py

#### IrModelFields — `ir.model.fields` (`_name`)

Field metadata registry — one record per field per model.

**Fields:**
- `name` (Char, required, indexed) — Field technical name
- `model` (Char, required, indexed), `model_id` (Many2one → ir.model, required)
- `field_description` (Char, required, translatable) — Human label
- `ttype` (Selection, required) — Field type (char, text, boolean, integer, float, monetary, date, datetime, one2many, many2one, many2many, selection, reference, html, binary, image, properties)
- `relation` (Char) — Comodel for relational fields
- `relation_field` (Char) — Inverse field for one2many
- `selection_ids` (One2many → ir.model.fields.selection)
- `related` (Char) — Dot-separated related field path
- `required`, `readonly`, `index` (Boolean)
- `translate` (Selection) — `standard`, `html_translate`, `xml_translate`
- `company_dependent` (Boolean)
- `state` (Selection) — `manual` or `base`
- `on_delete` (Selection) — `cascade`, `set null`, `restrict`
- `store` (Boolean, default=True), `compute` (Text), `depends` (Char)

**Key Methods:**
- `_get(model_name, field_name)` — Get field record
- `_get_ids(model_name)` — Get `{field_name: field_id}` dict
- `_reflect_fields(model_names)` — Sync field metadata from registry to DB

---

### models/ir_model_fields_selection.py

#### IrModelFieldsSelection — `ir.model.fields.selection` (`_name`)

Selection field options.

**Fields:**
- `field_id` (Many2one → ir.model.fields, required, indexed)
- `value` (Char, required), `name` (Char, required, translatable)
- `sequence` (Integer, default=1000)

**Key Methods:**
- `_get_selection(field_id)` — Get `[(value, name), ...]` for field
- `_reflect_selections(model_names)` — Sync selections from field definitions
- `_update_selection(model_name, field_name, selection)` — Insert/update/delete options
- `_process_ondelete()` — Handle ondelete policies when selection removed

---

### models/ir_model_access.py

Contains three models: access control, constraints, and relations.

#### IrModelAccess — `ir.model.access` (`_name`)

Model-level access control lists.

**Fields:**
- `name` (Char, required, indexed), `active` (Boolean, default=True)
- `model_id` (Many2one → ir.model, required, indexed)
- `group_id` (Many2one → res.groups, indexed) — NULL = global access
- `perm_read`, `perm_write`, `perm_create`, `perm_unlink` (Boolean)

**Key Methods:**
- `check(model, mode, raise_exception)` — Check current user has access
- `_get_access_groups(model_name, access_mode)` — Get group expression (ormcache)
- `_get_allowed_models(mode)` — Models accessible to current user (ormcache)
- `group_names_with_access(model_name, access_mode)` — Visible group names with access
- `_make_access_error(model, mode)` — Build detailed AccessError message

#### IrModelConstraint — `ir.model.constraint` (`_name`)

Tracks database constraints created by models.

**Fields:**
- `name` (Char, required), `definition` (Char) — PostgreSQL constraint text
- `message` (Char, translatable) — Error message
- `model` (Many2one → ir.model), `module` (Many2one → ir.module.module)
- `type` (Char, size=1) — `f` (FK), `u` (unique/check), `i` (index)

**Key Methods:**
- `_reflect_constraints(model_names)` — Sync constraints from registry
- `unlink()` — Drop constraint from database

#### IrModelRelation — `ir.model.relation` (`_name`)

Tracks many2many relation tables.

**Fields:**
- `name` (Char, required) — M2M table name
- `model` (Many2one → ir.model), `module` (Many2one → ir.module.module)

**Key Methods:**
- `_module_data_uninstall()` — Drop M2M tables on module uninstall

---

### models/ir_model_data.py

#### IrModelData — `ir.model.data` (`_name`)

XML ID registry — maps external identifiers to database records.

**Fields:**
- `name` (Char, required) — ID suffix
- `complete_name` (Char, computed) — `module.name`
- `model` (Char, required) — Target model name
- `module` (Char, default=`""`, required) — Module prefix
- `res_id` (Many2oneReference) — Target record ID
- `noupdate` (Boolean) — Skip updates on module upgrade

**Key Methods:**
- `_xmlid_lookup(xmlid)` — Returns `(model, res_id)` (ormcache)
- `_xmlid_to_res_model_res_id(xmlid, raise_if_not_found)` — Safe wrapper
- `_xmlid_to_res_id(xmlid, raise_if_not_found)` — Extract just res_id
- `check_object_reference(module, xml_id, raise_on_access_error)` — Access check
- `_update_xmlids(data_list, update)` — Batch create/update XML IDs
- `_module_data_uninstall(modules_to_remove)` — Delete records by module on uninstall

---

## Access Control

### models/ir_rule.py

#### IrRule — `ir.rule` (`_name`)

Record-level access rules — domain-based filtering per model/group/operation.

**Fields:**
- `name` (Char), `active` (Boolean, default=True)
- `model_id` (Many2one → ir.model, required, indexed)
- `groups` (Many2many → res.groups) — NULL = global rule
- `domain_force` (Text) — Rule domain expression
- `perm_read`, `perm_write`, `perm_create`, `perm_unlink` (Boolean, default=True)

**Key Methods:**
- `_compute_domain(model_name, mode)` — Compute effective domain for current user (ormcache)
- `_get_rules(model_name, mode)` — Get applicable rules
- `_get_failing(for_records, mode)` — Get rules failing on specific records
- `_eval_context()` — Build safe_eval context (user, company_ids, company_id)

---

## UI Framework

### models/ir_ui_view.py

#### IrUiView — `ir.ui.view` (`_name`)

View definitions — the core UI building block.

**Fields:**
- `name` (Char, required), `model` (Char, indexed) — Target model
- `key` (Char, indexed) — Unique view key
- `priority` (Integer, default=16) — Lower = higher priority
- `type` (Selection) — list, form, graph, pivot, calendar, kanban, search, qweb
- `arch` (Text, computed/inverse) — View arch with translations
- `arch_base` (Text, computed/inverse) — Arch without translations
- `arch_db` (Text, translatable) — Stored arch
- `arch_fs` (Char) — File path if from XML
- `arch_prev` (Text) — Previous arch for rollback
- `inherit_id` (Many2one → self, indexed) — Parent view
- `inherit_children_ids` (One2many → self)
- `mode` (Selection) — `primary` or `extension`
- `active` (Boolean, default=True)
- `group_ids` (Many2many → res.groups) — NULL = all users

**Key Methods:**
- `apply_inheritance_specs(source, specs_tree, pre_locate)` — Apply XPath inheritance spec
- `_validate_view(arch)` — Validate arch (groups, fields, actions)
- `_render_template(arch_tree, values, ...)` — Render arch through QWeb

### models/ir_ui_view_base.py

#### Base — `_inherit = 'base'` (extends all models)

Default view generators, view access, and access helpers.

**Key Methods:**
- `get_view(view_id, view_type, **options)` — Get view with inheritance applied
- `get_views(views, options)` — Load multiple views at once
- `get_empty_list_help(help_message)` — Hook for empty list message
- `_get_default_form_view()` — Auto-generate form view
- `_get_default_search_view()` — Auto-generate search view
- `_get_default_list_view()`, `_get_default_kanban_view()`, `_get_default_pivot_view()`, `_get_default_graph_view()`, `_get_default_calendar_view()`
- `_get_access_action(access_uid, force_website)` — Hook for record access action

### models/ir_ui_view_custom.py

#### IrUiViewCustom — `ir.ui.view.custom` (`_name`)

User-specific view customizations (Copy-on-Write).

**Fields:**
- `ref_id` (Many2one → ir.ui.view, required), `user_id` (Many2one → res.users, required)
- `arch` (Text, required) — Custom arch

### models/ir_ui_view_name_manager.py

#### NameManager (utility class, not ORM model)

Validates view XML structure: fields, actions, groups, names.

**Key Methods:**
- `has_field(node, name, node_info, info)` — Register available field
- `must_have_fields(node, names, node_info, use)` — Declare field dependency
- `check(view)` — Validate all dependencies exist + group consistency

---

### models/ir_ui_menu.py

#### IrUiMenu — `ir.ui.menu` (`_name`, `_parent_store = True`)

Menu tree — hierarchical navigation.

**Fields:**
- `name` (Char, required, translatable)
- `active` (Boolean, default=True), `sequence` (Integer, default=10)
- `child_id` (One2many → self), `parent_id` (Many2one → self, indexed)
- `parent_path` (Char, indexed)
- `group_ids` (Many2many → res.groups) — NULL = visible to all
- `web_icon` (Char), `web_icon_data` (Binary, attachment)
- `action` (Reference → ir.actions.*) — Linked action

**Key Methods:**
- `_visible_menu_ids(debug)` — Get visible menu IDs for current user (ormcache)
- `_filter_visible_menus()` — Filter to visible menus

---

### models/ir_asset.py

#### IrAsset — `ir.asset` (`_name`)

Asset bundle management — controls JS/CSS/SCSS file inclusion.

**Fields:**
- `name` (Char, required), `bundle` (Char, required) — Target bundle name
- `directive` (Selection, required) — `append`, `prepend`, `after`, `before`, `remove`, `replace`, `include`
- `path` (Char, required) — Glob pattern for files
- `target` (Char) — For after/before/replace directives
- `active` (Boolean, default=True), `sequence` (Integer, default=16)

**Key Methods:**
- `_get_asset_paths(bundle, assets_params)` — Fetch all asset paths for bundle
- `_fill_asset_paths(bundle, asset_paths, ...)` — Recursively resolve includes
- `_process_path(bundle, directive, target, ...)` — Apply directive
- `_get_asset_bundle_url(filename, unique, ...)` — Generate asset URL
- `_topological_sort(addons_tuple)` — Dependency-based addon ordering

---

### models/assetsbundle.py

#### AssetsBundle (non-ORM class)

Asset compilation engine — concatenates, minifies, and bundles JS/CSS/SCSS.

**Constructor:** `__init__(name, files, external_assets, env, css, js, debug_assets, rtl, assets_params, autoprefix)`

**Key Methods:**
- `get_links()` — List of (url, content) tuples for rendered assets
- `get_link(asset_type)` — Single compiled bundle link

**Asset Classes:** `JavascriptAsset`, `StylesheetAsset`, `ScssStylesheetAsset`, `LessStylesheetAsset`, `XMLAsset`

---

## Templating

### models/ir_qweb.py

#### IrQweb — `ir.qweb` (AbstractModel)

QWeb template engine — compiles XML templates to Python functions, renders to Markup.

**Key Methods:**
- `_render(template, values, ...)` — Main render entry point → Markup string
- `_compile(template, options, ...)` — Compile template to Python function (ormcache)
- `_compile_node(node, options, indent, ...)` — Recursively compile XML node
- `_compile_directive_if()`, `_compile_directive_foreach()`, `_compile_directive_set()`, `_compile_directive_call()`, `_compile_directive_out()`, `_compile_directive_field()` — Directive handlers
- `_get_field(...)` — Get field value with widget formatting
- `_eval_expr(expr, values)` — Evaluate Python expression safely

### models/ir_qweb_fields.py

#### IrQwebField — `ir.qweb.field` (AbstractModel, 21 subclasses)

QWeb field value formatters — one subclass per field type.

**Base Methods:**
- `value_to_html(value, options)` — Format value to HTML string
- `record_to_html(record, field_name, options)` — Get value + format
- `attributes(record, field_name, options, values)` — Generate data-oe-* attributes

**Subclasses:** IrQwebFieldInteger, IrQwebFieldFloat, IrQwebFieldDate, IrQwebFieldDatetime, IrQwebFieldText, IrQwebFieldHtml, IrQwebFieldMonetary, IrQwebFieldSelection, IrQwebFieldMany2one, IrQwebFieldMany2many, IrQwebFieldOne2many, IrQwebFieldImage, IrQwebFieldImage_Url, IrQwebFieldBarcode, IrQwebFieldFloat_Time, IrQwebFieldTime, IrQwebFieldDuration, IrQwebFieldRelative, IrQwebFieldContact, IrQwebFieldQweb

---

## Scheduling

### models/ir_cron.py

#### IrCron — `ir.cron` (`_name`, `_inherits = {'ir.actions.server': 'ir_actions_server_id'}`)

Scheduled jobs — executes server actions on a recurring schedule.

**Fields:**
- `ir_actions_server_id` (Many2one, delegate, required) — Linked server action
- `cron_name` (Char, computed/stored)
- `user_id` (Many2one → res.users, required)
- `active` (Boolean, default=True)
- `interval_number` (Integer, default=1), `interval_type` (Selection) — minutes/hours/days/weeks/months
- `nextcall` (Datetime, required), `lastcall` (Datetime)
- `priority` (Integer, default=5)
- `failure_count` (Integer), `first_failure_date` (Datetime)

**Key Methods:**
- `_process_jobs(db_name)` — Static: execute ready jobs
- `_acquire_one_job(cr, job_id, include_not_ready)` — Lock job for execution (SELECT FOR UPDATE)
- `_callback(cron_name, server_action_id)` — Run the server action
- `_trigger(at)`, `_trigger_list(at_list)` — Schedule immediate execution
- `_notifydb()` — Wake cron workers via pg_notify
- `method_direct_trigger()` — Run cron immediately (UI button)
- `toggle(model, domain)` — Toggle active state conditionally

#### IrCronTrigger — `ir.cron.trigger` (`_name`)

One-shot triggers that wake a cron job early.

**Fields:**
- `cron_id` (Many2one → ir.cron, required, cascade), `call_at` (Datetime, required)

#### IrCronProgress — `ir.cron.progress` (`_name`)

Progress tracking for long-running cron jobs.

**Fields:**
- `cron_id` (Many2one → ir.cron, required, cascade)
- `remaining` (Integer), `done` (Integer), `deactivate` (Boolean)

---

## Storage and Streaming

### models/ir_attachment.py

#### IrAttachment — `ir.attachment` (`_name`)

File storage — supports both database and filestore backends.

**Fields:**
- `name` (Char, required), `description` (Text)
- `res_model` (Char), `res_field` (Char), `res_id` (Many2oneReference)
- `company_id` (Many2one → res.company)
- `type` (Selection, required) — `url` or `binary`
- `url` (Char, indexed), `public` (Boolean), `access_token` (Char)
- `raw` (Binary, computed/inverse) — Raw bytes
- `datas` (Binary, computed/inverse) — Base64 encoded
- `db_datas` (Binary) — Database storage field
- `store_fname` (Char, indexed) — Filestore path
- `file_size` (Integer), `checksum` (Char, size=40), `mimetype` (Char)
- `index_content` (Text) — Extracted text for full-text search

**Key Methods:**
- `_storage()` — Returns `file` or `db` (from config)
- `_filestore()` — Filestore directory path
- `force_storage()` — Migrate all attachments to configured storage
- `_file_read(fname, size)`, `_file_write(bin_value, checksum)`, `_file_delete(fname)`
- `_gc_file_store()` — Autovacuum garbage collection
- `_compute_mimetype(values)` — Detect MIME type
- `_postprocess_contents(values)` — Image auto-resizing
- `create_unique(values_list)` — Create only if checksum+size unique
- `generate_access_token()` — Generate scoped access tokens
- `_get_serve_attachment(url, extra_domain, order)` — Find attachment by URL
- `_from_request_file(file, mimetype, ...)` — Create from HTTP upload
- `_to_http_stream()` — Convert to Stream for download

### models/ir_binary.py

#### IrBinary — `ir.binary` (AbstractModel)

File streaming helpers for download/image endpoints.

**Key Methods:**
- `_find_record(xmlid, res_model, res_id, access_token, field)` — Find record for streaming
- `_record_to_stream(record, field_name)` — Convert field to Stream
- `_get_stream_from(record, field_name, filename, ...)` — Create download stream
- `_get_image_stream_from(record, field_name, ...)` — Image stream with resizing
- `_get_placeholder_stream(path)` — Placeholder image stream

---

## Sequences

### models/ir_sequence.py

#### IrSequence — `ir.sequence` (`_name`)

Auto-incrementing sequences — manages PostgreSQL sequences.

**Fields:**
- `name` (Char, required), `code` (Char) — Sequence code
- `implementation` (Selection) — `standard` (gapless reads) or `no_gap` (serialized)
- `prefix`, `suffix` (Char) — Pattern with date interpolation
- `number_next` (Integer, default=1), `number_increment` (Integer, default=1)
- `padding` (Integer, default=0)
- `company_id` (Many2one → res.company)
- `use_date_range` (Boolean), `date_range_ids` (One2many → ir.sequence.date_range)

**Key Methods:**
- `next_by_id(sequence_id)` — Get next value by ID
- `next_by_code(sequence_code)` — Get next value by code
- `_get_current_sequence(sequence_date)` — Get sequence or date-range subsequence
- `create(vals_list)` — Create PostgreSQL sequence if standard implementation
- `write(vals)` — Alter PostgreSQL sequence

---

## Configuration and Defaults

### models/ir_config_parameter.py

#### IrConfigParameter — `ir.config_parameter` (`_name`, `_rec_name = key`)

System parameters — key-value configuration store.

**Fields:**
- `key` (Char, required, unique), `value` (Text, required)

**Key Methods:**
- `init(force)` — Initialize default parameters (database.secret, database.uuid, web.base.url, etc.)
- `get_param(key, default)` — Retrieve parameter value
- `set_param(key, value)` — Set or create parameter
- `_get_param(key)` — Cached parameter fetch (ormcache)

### models/ir_default.py

#### IrDefault — `ir.default` (`_name`)

Default field values — per-user, per-company, per-condition.

**Fields:**
- `field_id` (Many2one → ir.model.fields, required, cascade)
- `user_id` (Many2one → res.users, cascade) — NULL = all users
- `company_id` (Many2one → res.company, cascade) — NULL = all companies
- `condition` (Char), `json_value` (Char, required)

**Key Methods:**
- `set(model_name, field_name, value, user_id, company_id, condition)` — Set default
- `_get(model_name, field_name, user_id, company_id, condition)` — Retrieve default
- `_get_model_defaults(model_name, condition)` — Cached defaults per model
- `discard_records(records)`, `discard_values(model_name, field_name, values)` — Clear defaults

### models/ir_filters.py

#### IrFilters — `ir.filters` (`_name`)

Saved search filters.

**Fields:**
- `name` (Char, required), `user_ids` (Many2many → res.users) — Empty = shared
- `domain` (Text, required), `context` (Text, required), `sort` (Char, required)
- `model_id` (Selection) — Target model
- `is_default` (Boolean), `active` (Boolean, default=True)
- `action_id` (Many2one → ir.actions.actions)
- `embedded_action_id` (Many2one → ir.embedded.actions)

**Key Methods:**
- `get_filters(model, action_id, embedded_action_id, ...)` — Retrieve user's filters
- `create_filter(vals)` — Create filter with validation

### models/ir_exports.py

#### IrExports — `ir.exports` (`_name`)

Saved export field presets.

**Fields:**
- `name` (Char), `resource` (Char, indexed)
- `export_fields` (One2many → ir.exports.line)

#### IrExportsLine — `ir.exports.line` (`_name`)

**Fields:** `name` (Char), `export_id` (Many2one → ir.exports, cascade)

---

## HTTP and Routing

### models/ir_http.py

#### IrHttp — `ir.http` (AbstractModel)

HTTP routing, authentication, and request dispatch.

**Key Methods:**
- `routing_map(key)` — Generate and cache routing map for installed modules (ormcache)
- `_match(path_info)` — Match HTTP path to routing rule
- `_authenticate(endpoint)` — Authenticate request based on endpoint auth type
- `_auth_method_none()`, `_auth_method_user()`, `_auth_method_public()`, `_auth_method_bearer()` — Auth handlers
- `_pre_dispatch(rule, args)` — Pre-dispatch hook (upload limits, language)
- `_dispatch(endpoint)` — Execute endpoint with reCAPTCHA verification
- `_post_dispatch(response)` — Post-dispatch hook
- `_handle_error(exception)` — Error handler
- `_serve_fallback()` — Serve files from attachments
- `_get_translations_for_webclient(modules, lang)` — Translations for JS
- `_slugify(value, max_length, path)` — URL slug generation
- `_slug(value)` — Record to slug, `_unslug(value)` — Slug to (prefix, id)

---

## Mail

### models/ir_mail_server.py

#### IrMailServer — `ir.mail.server` (`_name`)

SMTP server configuration and email sending.

**Fields:**
- `name` (Char, required), `from_filter` (Char) — Domain/email filters
- `smtp_host`, `smtp_port` (Char, Integer)
- `smtp_authentication` (Selection) — `login`, `certificate`, `cli`
- `smtp_user`, `smtp_pass` (Char, groups=system)
- `smtp_encryption` (Selection) — `none`, `starttls`, `ssl` (with variants)
- `smtp_ssl_certificate`, `smtp_ssl_private_key` (Binary)
- `smtp_debug` (Boolean), `max_email_size` (Float)
- `sequence` (Integer, default=10), `active` (Boolean, default=True)

**Key Methods:**
- `_connect(host, port, user, password, encryption, ...)` — Create SMTP connection
- `_build_email(email_from, email_to, subject, body, ...)` — Build RFC2822 EmailMessage
- `send_email(message, mail_server_id, ...)` — Send email via SMTP
- `_find_mail_server(email_from, mail_servers)` — Find server by FROM address
- `test_smtp_connection(autodetect_max_email_size)` — Test connection

---

## Module System

### models/ir_module.py

#### IrModuleCategory — `ir.module.category` (`_name`)

Module categories (application groups).

**Fields:**
- `name` (Char, required, translatable), `parent_id` (Many2one → self)
- `child_ids` (One2many), `module_ids` (One2many → ir.module.module)
- `privilege_ids` (One2many → res.groups.privilege)
- `sequence` (Integer), `visible` (Boolean, default=True), `exclusive` (Boolean)

#### IrModuleModule — `ir.module.module` (`_name`)

Module lifecycle management.

**Fields:**
- `name` (Char), `shortdesc` (Char, translatable), `summary` (Char, translatable)
- `author` (Char), `website` (Char)
- `state` (Selection) — installed, uninstalled, to upgrade, to remove, to install
- `category_id` (Many2one → ir.module.category)
- `dependencies_id` (One2many → ir.module.module.dependency)
- `application` (Boolean), `installable` (Boolean), `auto_install` (Boolean)
- `installed_version` (Char), `latest_version` (Char, computed)
- `license` (Selection)

**Key Methods:**
- `button_install()`, `button_uninstall()`, `button_upgrade()`, `button_immediate_upgrade()`
- `get_module_info(name)` — Read manifest metadata
- `update_list()` — Scan filesystem for new/updated modules

---

## Logging and Profiling

### models/ir_logging.py

#### IrLogging — `ir.logging` (`_name`)

Server/client log storage (bypasses ORM for performance).

**Fields:**
- `name` (Char), `type` (Selection: `client`/`server`), `dbname` (Char)
- `level` (Char), `message` (Text), `path` (Char), `func` (Char), `line` (Char)

### models/ir_profile.py

#### IrProfile — `ir.profile` (`_name`)

Code profiling with Speedscope output.

**Fields:**
- `session` (Char), `name` (Char), `duration`, `cpu_duration` (Float)
- `sql` (Text), `traces_async`, `traces_sync` (Text)
- `sql_count`, `entry_count` (Integer)
- `speedscope` (Binary, computed), `speedscope_url` (Text, computed)

**Key Methods:**
- `set_profiling(profile, collectors, params)` — Enable/disable profiling
- `_gc_profile()` — Autovacuum profiles older than 30 days

---

## Import

### models/ir_fields.py

#### IrFieldsConverter — `ir.fields.converter` (AbstractModel)

Data import type conversion — converts external data formats to ORM field values.

**Key Methods:**
- `for_model(model, fromtype, savepoint)` — Returns converter function for model
- `to_field(model, field, fromtype, savepoint)` — Field-specific converter
- `db_id_for(model, field, subfield, value, savepoint)` — Find database ID by reference
- `_str_to_boolean()`, `_str_to_integer()`, `_str_to_float()`, `_str_to_date()`, `_str_to_datetime()`, `_str_to_selection()`, `_str_to_many2one()`, `_str_to_many2many()`, `_str_to_one2many()`, `_str_to_json()`, `_str_to_properties()`

---

## Embedded Actions

### models/ir_embedded_actions.py

#### IrEmbeddedActions — `ir.embedded.actions` (`_name`)

Actions embedded within views (tabs, sub-views).

**Fields:**
- `name` (Char, translatable), `sequence` (Integer)
- `parent_action_id` (Many2one → ir.actions.act_window, required, cascade)
- `parent_res_id` (Integer), `parent_res_model` (Char, required)
- `action_id` (Many2one → ir.actions.actions, cascade)
- `python_method` (Char) — Alternative: method returning action
- `user_id` (Many2one → res.users) — NULL = shared
- `is_deletable` (Boolean, computed), `is_visible` (Boolean, computed)
- `domain` (Char), `context` (Char), `groups_ids` (Many2many → res.groups)

---

## Autovacuum

### models/ir_autovacuum.py

#### IrAutovacuum — `ir.autovacuum` (AbstractModel)

Garbage collection framework.

**Key Methods:**
- `_run_vacuum_cleaner()` — Execute all `@api.autovacuum` methods across all models
- `_gc_orm_signaling()` — Garbage collection on ORM signaling tables

---

## Demo Data

### models/ir_demo.py / ir_demo_failure.py

#### IrDemo — `ir.demo` (TransientModel)

**Key Methods:** `install_demo()` — Force demo data installation

#### IrDemoFailure — `ir.demo_failure` (TransientModel)

**Fields:** `module_id` (Many2one → ir.module.module), `error` (Char)

#### IrDemoFailureWizard — `ir.demo_failure.wizard` (TransientModel)

**Fields:** `failure_ids` (One2many), `failures_count` (Integer, computed)

---

## Partners

### models/res_partner.py

#### ResPartner — `res.partner` (`_name`, `_parent_store = True`)

Core business entity — contacts, companies, addresses.
Inherits: `format.address.mixin`, `format.vat.label.mixin`, `avatar.mixin`, `properties.base.definition.mixin`

**Fields (key selection):**
- `name` (Char, indexed), `complete_name` (Char, computed, indexed)
- `parent_id` (Many2one → self), `child_ids` (One2many → self)
- `ref` (Char, indexed) — Internal reference
- `lang` (Selection, computed, stored, readonly=False) — Language
- `tz` (Selection) — Timezone
- `user_id` (Many2one → res.users, computed, precompute, readonly=False, stored) — Salesperson
- `vat` (Char, indexed), `company_registry` (Char)
- `bank_ids` (One2many → res.partner.bank)
- `category_id` (Many2many → res.partner.category) — Tags
- `active` (Boolean, default=True)
- `type` (Selection) — `contact`, `invoice`, `delivery`, `other`
- Address fields: `street`, `street2`, `zip`, `city`, `state_id`, `country_id`
- `partner_latitude`, `partner_longitude` (Float)
- `email`, `email_formatted` (Char), `phone` (Char)
- `is_company` (Boolean), `company_type` (Selection: person/company)
- `company_id` (Many2one → res.company)
- `commercial_partner_id` (Many2one, computed, stored, recursive, indexed)
- `commercial_company_name` (Char, computed, stored)
- `barcode` (Char, company_dependent)

**Key Methods:**
- `_compute_display_name()` — Format with company, type, address
- `name_search(name, domain, operator, limit)` — Search by name, ref, email, VAT
- `_get_complete_name()` — Build display name with company/type
- `_compute_avatar_*()` — Avatar computation (SVG or image)
- `_fields_sync(values)` — Sync fields between parent/child
- `_handle_first_contact_creation(partner)` — Auto-link children when parent created
- `create(vals_list)`, `write(vals)` — With partner_share computation, commercial field sync

### models/res_partner_category.py

#### ResPartnerCategory — `res.partner.category` (`_name`, `_parent_store = True`)

Partner tags — hierarchical.

**Fields:**
- `name` (Char, required, translatable), `color` (Integer)
- `active` (Boolean, default=True)
- `parent_id` (Many2one → self, cascade), `child_ids` (One2many)
- `parent_path` (Char, indexed) — Materialized path for `_parent_store`
- `partner_ids` (Many2many → res.partner)

### models/res_partner_industry.py

#### ResPartnerIndustry — `res.partner.industry` (`_name`)

**Fields:** `name` (Char, translatable), `full_name` (Char, translatable), `active` (Boolean)

### models/res_partner_format_address_mixin.py

#### FormatAddressMixin — `format.address.mixin` (AbstractModel)

Customizes address form layout based on country `address_view_id` or `address_format`.

**Key Methods:**
- `_view_get_address(arch)` — Customize address form view
- `_get_view()` — Override to apply address customization

### models/res_partner_format_vat_mixin.py

#### FormatVatLabelMixin — `format.vat.label.mixin` (AbstractModel)

Relabels VAT field based on company country's `vat_label`.

---

## Users

### models/res_users.py

#### ResUsers — `res.users` (`_name`, `_inherits = {'res.partner': 'partner_id'}`)

User accounts — inherits all partner fields.

**Fields (beyond partner):**
- `partner_id` (Many2one → res.partner, required)
- `login` (Char, required, unique)
- `password` (Char) — Hashed
- `new_password` (Char, computed/inverse) — For password changes
- `signature` (Html)
- `active` (Boolean, default=True)
- `groups_id` (Many2many → res.groups)
- `share` (Boolean, computed) — Non-internal user
- `companies_count` (Integer, computed)
- `company_id` (Many2one → res.company, required) — Current company
- `company_ids` (Many2many → res.company) — Allowed companies
- `action_id` (Many2one → ir.actions.actions) — Home action
- `notification_type` (Selection) — `email` or `inbox`

**Properties:**
- `SELF_READABLE_FIELDS` — Fields readable by user on own record
- `SELF_WRITEABLE_FIELDS` — Fields writable by user on own record

**Key Methods:**
- `_login(db, credential, user_agent_env)` — Authenticate user
- `_check_credentials(credential, env)` — Verify credentials
- `authenticate(db, credential, user_agent_env)` — Full auth flow
- `check_identity(fn)` — Decorator requiring password re-verification
- `_is_admin()`, `_is_system()`, `_is_superuser()` — Access level checks
- `has_group(group_ext_id)` — Check if user belongs to group
- `_change_password(new_passwd)` — Change password
- `action_reset_password()` — Send password reset email
- `_default_groups()` — Default groups (base.group_user + implied)

### models/res_users_apikeys.py

#### ResUsersApikeys — `res.users.apikeys` (`_name`, `_auto = False`)

API key management with custom SQL table (encrypted key storage).

**Fields:**
- `name` (Char), `user_id` (Many2one → res.users, cascade)
- `scope` (Char), `expiration_date` (Datetime)

**Key Methods:**
- `_check_credentials(*, scope, key)` — Verify API key
- `_generate(scope, name, expiration_date)` — Generate and store key
- `_gc_user_apikeys()` — Autovacuum expired keys

#### ResUsersApikeysDescription — `res.users.apikeys.description` (TransientModel)

API key creation wizard.

### models/res_users_identitycheck.py

#### ResUsersIdentitycheck — `res.users.identitycheck` (TransientModel)

Password verification wizard — used by `@check_identity` decorator.

**Key Methods:**
- `_check_identity()` — Verify password credential
- `run_check()` — Validate identity, execute deferred action

### models/res_users_log.py

#### ResUsersLog — `res.users.log` (`_name`)

Login tracking.
**Key Methods:** `_gc_user_logs()` — Keep only latest log per user

### models/res_users_deletion.py

#### ResUsersDeletion — `res.users.deletion` (`_name`)

User deletion queue.
**Key Methods:** `_gc_portal_users(batch_size=50)` — Cron: batch-delete queued users

### models/res_users_settings.py

#### ResUsersSettings — `res.users.settings` (`_name`, unique `user_id`)

Per-user settings storage.

**Key Methods:**
- `_find_or_create_for_user(user)` — Find or create settings record
- `set_res_users_settings(new_settings)` — Update and return formatted settings

---

## Companies

### models/res_company.py

#### ResCompany — `res.company` (`_name`, `_parent_store = True`)

Company hierarchy with branch support.

**Fields:**
- `name` (Char, related → partner.name, required, stored, readonly=False)
- `active` (Boolean, default=True), `sequence` (Integer)
- `parent_id` (Many2one → self), `child_ids`, `all_child_ids` (One2many)
- `root_id` (Many2one, computed) — Root company
- `partner_id` (Many2one → res.partner, required)
- `currency_id` (Many2one → res.currency, required)
- `user_ids` (Many2many → res.users)
- Address fields (computed from partner with inverses)
- Report styling: `font`, `primary_color`, `secondary_color`, `layout_background`
- `paperformat_id` (Many2one → report.paperformat)

**Key Methods:**
- `_get_company_root_delegated_field_names()` — Fields synced from root (currency_id)
- `_accessible_branches()` — Browse accessible branches for current user
- `_get_public_user()` — Get/create public user for company
- `create(vals_list)` — Auto-create partner, sync delegated fields, install l10n
- `write(vals)` — Enforce hierarchy, copy delegated fields to branches

---

## Security Groups

### models/res_groups.py

#### ResGroups — `res.groups` (`_name`)

Security groups with implication chains and disjoint constraints.

**Fields:**
- `name` (Char, required, translatable)
- `user_ids`, `all_user_ids` (Many2many → res.users)
- `comment` (Text, translatable)
- `full_name` (Char, computed) — `privilege / group`
- `share` (Boolean) — Non-internal group
- `api_key_duration` (Float) — Max API key duration (days)
- `sequence` (Integer)
- `privilege_id` (Many2one → res.groups.privilege)
- `implied_ids` (Many2many → res.groups) — Direct implications
- `all_implied_ids` (Many2many, computed) — Transitive closure
- `disjoint_ids` (Many2many) — Mutually exclusive groups

**Key Methods:**
- `_check_disjoint_groups()` — Prevent users having exclusive groups
- `_apply_group(implied_group)` — Add group to implications
- `_remove_group(implied_group)` — Remove group from implications
- `_get_user_type_groups()` — Return employee/portal/public disjoint groups
- `_get_group_definitions()` — Return SetDefinitions for closure computation
- `_is_feature_enabled(group_reference)` — Check superuser feature flag

### models/res_groups_privilege.py

#### ResGroupsPrivilege — `res.groups.privilege` (`_name`)

Group privilege categories (User Types, Features, etc.).

**Fields:**
- `name` (Char, required, translatable), `description` (Text)
- `placeholder` (Char, default=`No`) — Selection placeholder text
- `sequence` (Integer, default=100)
- `category_id` (Many2one → ir.module.category)
- `group_ids` (One2many → res.groups)

---

## Localization

### models/res_country.py

#### ResCountry — `res.country` (`_name`)

**Fields:**
- `name` (Char, required, translatable), `code` (Char, size=2, required)
- `address_format` (Text), `address_view_id` (Many2one → ir.ui.view)
- `currency_id` (Many2one → res.currency)
- `phone_code` (Integer)
- `country_group_ids` (Many2many → res.country.group)
- `state_ids` (One2many → res.country.state)
- `name_position` (Selection: before/after)
- `vat_label` (Char, translatable), `state_required`, `zip_required` (Boolean)

**Key Methods:**
- `name_search(name, ...)` — Search by 2-char code first, then name
- `get_address_fields()` — Extract field names from address_format

#### ResCountryGroup — `res.country.group` (`_name`)

**Fields:** `name` (Char, required, translatable), `code` (Char, unique), `country_ids` (Many2many)

#### ResCountryState — `res.country.state` (`_name`)

**Fields:** `country_id` (Many2one, required), `name` (Char, required), `code` (Char, required)

### models/res_currency.py

#### ResCurrency — `res.currency` (`_name`)

**Fields:**
- `name` (Char, size=3, required) — ISO 4217 code
- `symbol` (Char, required), `rounding` (Float, default=0.01)
- `rate`, `inverse_rate` (Float, computed from rate_ids)
- `decimal_places` (Integer, computed from rounding)
- `rate_ids` (One2many → res.currency.rate)
- `position` (Selection: after/before), `active` (Boolean, default=True)

**Key Methods:**
- `_get_rates(company, date)` — SQL subquery for exchange rates
- `round(amount)`, `compare_amounts(amount1, amount2)`, `is_zero(amount)`
- `_get_conversion_rate(from_currency, to_currency, company, date)` — Conversion rate
- `_convert(from_amount, to_currency, company, date, round)` — Convert amount
- `amount_to_text(amount)` — Textual representation (num2words)

#### ResCurrencyRate — `res.currency.rate` (`_name`)

**Fields:**
- `name` (Date, required), `rate` (Float) — Technical rate
- `company_rate`, `inverse_company_rate` (Float, computed/inverse)
- `currency_id` (Many2one, required, cascade), `company_id` (Many2one)

### models/res_lang.py

#### ResLang — `res.lang` (`_name`)

Language management and formatting.

**Fields:**
- `name` (Char, required), `code` (Char, required) — Locale code
- `iso_code` (Char), `url_code` (Char, required)
- `active` (Boolean), `direction` (Selection: ltr/rtl)
- `date_format`, `time_format` (Selection)
- `week_start` (Selection 1-7), `grouping` (Selection: international/indian)
- `decimal_point` (Char, default=`.`), `thousands_sep` (Char, default=`,`)

**Key Methods:**
- `_activate_lang(code)`, `_create_lang(lang, lang_name)` — Activate/create language
- `_get_data(**kwargs)` — Get LangData by field (ormcache)
- `get_installed()` — List of `(code, name)` tuples
- `format(percent, value, grouping)` — Language-specific number formatting

### models/res_bank.py

#### ResBank — `res.bank` (`_name`)

**Fields:** `name` (Char, required), `bic` (Char, indexed), address fields, `active` (Boolean)

#### ResPartnerBank — `res.partner.bank` (`_name`, `_rec_name = acc_number`)

Partner bank accounts.

**Fields:**
- `acc_number` (Char, required), `sanitized_acc_number` (Char, computed, stored)
- `partner_id` (Many2one → res.partner, required)
- `allow_out_payment` (Boolean), `bank_id` (Many2one → res.bank)
- `currency_id` (Many2one → res.currency)

**Key Methods:**
- `_compute_sanitized_acc_number()` — Remove non-word chars, uppercase
- `unlink()` — Archive instead of delete

---

## Devices

### models/res_device.py

#### ResDeviceLog — `res.device.log` (`_name`)

Device/session tracking.

**Fields:**
- `session_identifier` (Char, required), `platform`, `browser` (Char)
- `ip_address`, `country`, `city` (Char)
- `device_type` (Selection: computer/mobile)
- `user_id` (Many2one → res.users), `first_activity`, `last_activity` (Datetime)
- `revoked` (Boolean), `is_current` (Boolean, computed)

**Key Methods:**
- `_update_device(request)` — Log device info from HTTP request
- `_gc_device_log()` — Autovacuum old device logs

#### ResDevice — `res.device` (`_name`, `_auto = False`, SQL view)

Latest device per session/platform/browser (aggregated view).

**Key Methods:**
- `revoke()` — Revoke device session (`@check_identity` decorated)
- `_revoke()` — Delete from session store, mark revoked

---

## Mixins

### models/image_mixin.py

#### ImageMixin — `image.mixin` (AbstractModel)

Multi-resolution image fields.

**Fields:** `image_1920` (Image, max 1920), `image_1024`, `image_512`, `image_256`, `image_128` (computed, stored, auto-resized)

### models/avatar_mixin.py

#### AvatarMixin — `avatar.mixin` (AbstractModel, inherits `image.mixin`)

SVG avatar generation from name initials.

**Fields:** `avatar_1920`, `avatar_1024`, `avatar_512`, `avatar_256`, `avatar_128` (Image, computed)

**Key Methods:**
- `_compute_avatar(avatar_field, image_field)` — Use image or generate SVG
- `_avatar_generate_svg()` — Generate SVG with initials and HSL color

### models/properties_base_definition.py / properties_base_definition_mixin.py

#### PropertiesBaseDefinition — `properties.base.definition` (`_name`)

Properties field definition storage.

**Fields:**
- `properties_field_id` (Many2one → ir.model.fields, required, unique, cascade)
- `properties_definition` (PropertiesDefinition)

#### PropertiesBaseDefinitionMixin — `properties.base.definition.mixin` (AbstractModel)

Adds properties support to any model.

### models/decimal_precision.py

#### DecimalPrecision — `decimal.precision` (`_name`)

**Fields:** `name` (Char, required, unique), `digits` (Integer, required, default=2)
**Key Methods:** `precision_get(application)` — Cached lookup of digits (ormcache)

### models/report_layout.py / report_paperformat.py

#### ReportLayout — `report.layout` (`_name`)

**Fields:** `view_id` (Many2one → ir.ui.view, required), `image`, `pdf` (Char), `sequence` (Integer)

#### ReportPaperformat — `report.paperformat` (`_name`)

**Fields:** `name` (Char, required), `format` (Selection, default=A4), `orientation` (Selection), margins (top/bottom/left/right Float), `header_spacing` (Integer, mm — used by DIN5008 templates), `css_margins` (Boolean — WeasyPrint body-padding mode), `dpi` (Integer — Web Studio preview zoom), `disable_shrinking` (Boolean — Web Studio preview)

---

## Config

### models/res_config.py

#### ResConfig — `res.config` (TransientModel)

Base configuration wizard. Override `execute()` to save settings.

#### ResConfigSettings — `res.config.settings` (TransientModel)

Settings wizard framework with automatic field handling. Fields with naming conventions:
- `default_*` — Set default values for model fields
- `group_*` — Toggle group membership
- `module_*` — Install/uninstall modules
- `config_parameter` attribute — Read/write ir.config_parameter

**Key Methods:**
- `_get_classified_fields(fnames)` — Classify fields by type
- `default_get(fields)` — Load current values
- `set_values()` — Save defaults, apply groups, set config parameters
- `execute()` — Save settings and handle module installation

---

## Wizards

### wizard/base_partner_merge.py

#### BasePartnerMergeAutomaticWizard — `base.partner.merge.automatic.wizard` (TransientModel)

Partner deduplication — manual or automatic merge.

**Key Methods:**
- `_update_foreign_keys(src_partners, dst_partner)` — Update all FK references
- `_update_reference_fields(src_partners, dst_partner)` — Update reference fields
- `_merge(partner_ids, dst_partner, extra_checks)` — Core merge orchestration
- `action_start_manual_process()`, `action_start_automatic_process()` — Launch modes

### wizard/change_password.py

#### ChangePasswordWizard, ChangePasswordUser, ChangePasswordOwn (TransientModels)

Password change wizards — admin batch change and self-service.

### wizard/base_language_install.py / base_import_language.py / base_export_language.py

Language management wizards — install, import PO files, export translations.

### wizard/base_module_update.py / base_module_upgrade.py / base_module_uninstall.py

Module lifecycle wizards — scan, upgrade, uninstall with dependency analysis.

### wizard/reset_view_arch.py

#### ResetViewArchWizard — `reset.view.arch.wizard` (TransientModel)

Reset view to original arch — soft (arch_prev) or hard (arch_fs).

### wizard/wizard_ir_model_menu_create.py

#### WizardIrModelMenuCreate — `wizard.ir.model.menu.create` (TransientModel)

Create menu item for custom model.

---

## Model Index

Quick lookup — file → model → primary role:

| File | Model(s) | Role |
|------|----------|------|
| `ir_actions.py` | ir.actions.actions, .act_window, .act_url, .client, .todo, .act_window_close, .act_window.view | All action types |
| `ir_actions_report.py` | ir.actions.report | PDF/HTML report rendering (WeasyPrint) |
| `ir_actions_server.py` | ir.actions.server, .server.history, server.action.history.wizard | Automated actions (code/CRUD/webhook) |
| `ir_asset.py` | ir.asset | Asset bundle management |
| `ir_attachment.py` | ir.attachment | File storage (DB/filestore) |
| `ir_autovacuum.py` | ir.autovacuum | GC framework (@api.autovacuum) |
| `ir_binary.py` | ir.binary | File/image streaming helpers |
| `ir_config_parameter.py` | ir.config_parameter | System key-value parameters |
| `ir_cron.py` | ir.cron, .cron.trigger, .cron.progress | Scheduled jobs + triggers |
| `ir_default.py` | ir.default | Field default values |
| `ir_demo.py` | ir.demo | Demo data installation |
| `ir_demo_failure.py` | ir.demo_failure, .demo_failure.wizard | Demo failure tracking |
| `ir_embedded_actions.py` | ir.embedded.actions | Embedded view actions |
| `ir_exports.py` | ir.exports, ir.exports.line | Export presets |
| `ir_fields.py` | ir.fields.converter | Import type converters |
| `ir_filters.py` | ir.filters | Saved search filters |
| `ir_http.py` | ir.http | HTTP routing/auth/dispatch |
| `ir_logging.py` | ir.logging | Server/client logs |
| `ir_mail_server.py` | ir.mail.server | SMTP configuration/sending |
| `ir_model.py` | ir.model, ir.model.inherit | Model registry + inheritance |
| `ir_model_access.py` | ir.model.access, .constraint, .relation | ACL + DB constraint tracking |
| `ir_model_data.py` | ir.model.data | XML ID registry |
| `ir_model_fields.py` | ir.model.fields | Field metadata registry |
| `ir_model_fields_selection.py` | ir.model.fields.selection | Selection options |
| `ir_module.py` | ir.module.module, .category | Module lifecycle |
| `ir_profile.py` | ir.profile | Code profiling |
| `ir_qweb.py` | ir.qweb | Template engine |
| `ir_qweb_fields.py` | ir.qweb.field (+ 21 subclasses) | Template field formatters |
| `ir_rule.py` | ir.rule | Record-level access rules |
| `ir_sequence.py` | ir.sequence, .date_range | Auto-incrementing sequences |
| `ir_ui_menu.py` | ir.ui.menu | Menu hierarchy |
| `ir_ui_view.py` | ir.ui.view | View definitions + inheritance |
| `ir_ui_view_base.py` | base (mixin) | Default view generators |
| `ir_ui_view_custom.py` | ir.ui.view.custom | User view customizations |
| `ir_ui_view_name_manager.py` | NameManager (utility) | View XML validator |
| `assetsbundle.py` | AssetsBundle (non-ORM) | Asset compilation |
| `avatar_mixin.py` | avatar.mixin | SVG avatar generation |
| `decimal_precision.py` | decimal.precision | Decimal precision config |
| `image_mixin.py` | image.mixin | Multi-resolution images |
| `properties_base_definition.py` | properties.base.definition | Properties definitions |
| `properties_base_definition_mixin.py` | properties.base.definition.mixin | Properties mixin |
| `report_layout.py` | report.layout | Report templates |
| `report_paperformat.py` | report.paperformat | Paper format config |
| `res_bank.py` | res.bank, res.partner.bank | Banks + accounts |
| `res_company.py` | res.company | Company hierarchy |
| `res_config.py` | res.config, res.config.settings | Settings framework |
| `res_country.py` | res.country, .group, .state | Geography |
| `res_currency.py` | res.currency, .rate | Currencies + rates |
| `res_device.py` | res.device.log, res.device | Session tracking |
| `res_groups.py` | res.groups | Security groups |
| `res_groups_privilege.py` | res.groups.privilege | Group categories |
| `res_lang.py` | res.lang | Languages |
| `res_partner.py` | res.partner | Contacts/companies |
| `res_partner_category.py` | res.partner.category | Partner tags |
| `res_partner_format_address_mixin.py` | format.address.mixin | Address formatting |
| `res_partner_format_vat_mixin.py` | format.vat.label.mixin | VAT label formatting |
| `res_partner_industry.py` | res.partner.industry | Industries |
| `res_users.py` | res.users | User accounts |
| `res_users_apikeys.py` | res.users.apikeys, .description, .show | API keys |
| `res_users_deletion.py` | res.users.deletion | User deletion queue |
| `res_users_identitycheck.py` | res.users.identitycheck | Password verification |
| `res_users_log.py` | res.users.log | Login tracking |
| `res_users_settings.py` | res.users.settings | User preferences |
