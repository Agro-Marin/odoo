# Directory Map

> **238 entries** (237 subdirectories + `(root)`) | Maps directory → layer + responsibility
>
> Layers (Feature-Sliced Design): shared → entities → features → widgets → pages

| Directory | Layer | Files | Primary Responsibility |
|-----------|-------|------:|----------------------|
| `boot/` | misc | 2 | Entry point that launches the web client (replaced in enterprise) |
| `components/` | features | 2 | Reusable OWL UI components (pickers, dropdowns, editors, file handling) |
| `components/action_swiper/` | features | 1 | Touch swipe component that triggers actions on left/right swipe gestures |
| `components/autocomplete/` | features | 1 | Generic autocomplete dropdown with multi-source results, keyboard navigation,... |
| `components/barcode/` | features | 4 | BarcodeDetector polyfill built on ZXing for browsers without native support |
| `components/checkbox/` | features | 1 | Accessible checkbox component with label slot and hotkey support |
| `components/code_editor/` | features | 1 | Ace-based code editor component with syntax highlighting and theme support |
| `components/color_picker/` | features | 1 | Full-featured color picker with preset palette, custom colors, and gradient s... |
| `components/color_picker/custom_color_picker/` | features | 1 | HSL/RGB color picker with canvas gradient, sliders, and hex input |
| `components/color_picker/tabs/` | features | 2 | Color picker tab for custom color input with gradient support |
| `components/colorlist/` | features | 1 | Expandable color swatch picker for selecting from predefined Odoo color indices |
| `components/copy_button/` | features | 1 | Clipboard copy button with success tooltip feedback |
| `components/datetime/` | features | 4 | Date/time text input component that opens a DateTimePicker popover |
| `components/domain_selector/` | features | 3 | Visual domain builder that converts between string domains and tree editors |
| `components/domain_selector_dialog/` | features | 1 | Modal dialog for editing and validating an Odoo domain filter |
| `components/dropdown/` | features | 6 | Collapsible accordion panel with animated expand/collapse transitions |
| `components/dropdown/_behaviours/` | features | 3 | Hook that registers a dropdown within a DropdownGroup and tracks group open s... |
| `components/dropzone/` | features | 2 | Visual drop target overlay that tracks drag enter/leave and fires onDrop |
| `components/emoji_picker/` | features | 2 | Emoji data (generated) and picker UI with search and categories |
| `components/errors/` | features | 1 | Error dialog components for RPC, client, network, and validation errors |
| `components/expression_editor/` | features | 2 | Visual tree-based editor for Python expressions with field path selection |
| `components/expression_editor_dialog/` | features | 1 | Modal dialog for editing Python expressions with validation preview |
| `components/file_input/` | features | 1 | Customizable file upload input with route-based server upload and multi-file ... |
| `components/file_upload/` | features | 3 | Progress bar with cancel button for active file uploads |
| `components/file_viewer/` | features | 3 | FileModelMixin providing URL routing and type detection for viewable file att... |
| `components/model_field_selector/` | features | 2 | Field path selector with breadcrumb display and popover field browser |
| `components/model_selector/` | features | 1 | Autocomplete component for searching and selecting Odoo model names |
| `components/notebook/` | features | 1 | Tabbed notebook component that renders one page at a time with tab navigation |
| `components/pager/` | features | 2 | Pagination component with prev/next navigation and editable page range input |
| `components/record_selectors/` | features | 5 | Base class for record selector components with display name loading infrastru... |
| `components/resizable_panel/` | features | 1 | Side panel component with drag handle for interactive width resizing |
| `components/select_menu/` | features | 1 | Searchable dropdown select menu with multi-select tags and keyboard navigation |
| `components/signature/` | features | 2 | Signature pad component with draw, auto-generate, and load modes |
| `components/tags_list/` | features | 1 | Renders a list of colored tags with optional visibility limit and overflow co... |
| `components/time_picker/` | features | 1 | Time input component with dropdown hour/minute selection and configurable rou... |
| `components/tree_editor/` | features | 5 | UI-layer tree editor components (tree_editor, tree_editor_autocomplete, tree_editor_components, tree_editor_operator_editor, tree_editor_value_editors). Data-only tree-manipulation utilities live in `core/tree/`. |
| `components/user_switch/` | features | 1 | Login page component for quick-switching between recently connected user acco... |
| `core/` | shared | 15 | Framework primitives at the namespace root: registry, domain, context, parsers/formatters, templates, events, asset loading |
| `core/avatar/` | shared | 0 | Avatar component styles (SCSS only) |
| `core/badge/` | shared | 1 | Badge colour helpers (`badge_colors.js`) + component styles |
| `core/browser/` | shared | 7 | Prevents default scroll on bare "#" anchor clicks |
| `core/colors/` | shared | 1 | Predefined color palettes for charts and graph visualizations |
| `core/errors/` | shared | 4 | Traceback formatting, source-map annotation, and error chain utilities |
| `core/file_upload/` | shared | 1 | `FileHandler` component: hidden file input driving upload/drop flows, with its OWL template |
| `core/l10n/` | shared | 8 | Luxon-based date/datetime parsing, formatting, serialization, and locale-awar... |
| `core/l10n/utils/` | shared | 5 | Locale-aware list formatting via Intl.ListFormat (conjunction, disjunction, u... |
| `core/lib/` | shared | 2 | Lazy ESM loaders for import-map libraries: `chartjs.js` (`loadChartJS`) and `fullcalendar.js` (`loadFullCalendar`) — dynamic `import()` + live-bound exports; replaced `web.chartjs_lib` / `web.fullcalendar_lib` bundles |
| `core/network/` | shared | 6 | Content-Disposition header parser (RFC 6266/5987) |
| `core/position/` | shared | 2 | OWL hook for auto-repositioning a popper element relative to a target |
| `core/py_js/` | shared | 16 | Public API for parsing and evaluating Python expressions in JS |
| `core/tree/` | shared | 15 | Data-only condition-tree primitives: AST, conversions between domain ↔ tree ↔ Python expression, virtual operators. UI lives in `components/tree_editor/`. |
| `core/utils/` | shared | 22 | ErrorHandler component that catches child rendering errors |
| `core/utils/collections/` | shared | 3 | Array helpers: groupBy, sortBy, unique, intersection, cartesian, zip |
| `core/utils/dnd/` | shared | 7 | useDraggable OWL hook for free-form element dragging |
| `core/utils/dom/` | shared | 9 | useAutoresize hook to auto-grow input/textarea elements on content change |
| `core/utils/format/` | shared | 5 | Binary size detection, base64 length calculation, and human-readable byte for... |
| `fields/` | features | 14 | OWL hook that opens a dynamic placeholder popover on trigger key |
| `fields/basic/` | features | 3 | Abstract base class for numeric input fields with shared focus and parse logic |
| `fields/basic/boolean/` | features | 1 | Checkbox field widget for Boolean columns |
| `fields/basic/boolean_favorite/` | features | 1 | Star toggle field for marking records as favorites |
| `fields/basic/boolean_icon/` | features | 1 | Clickable icon field that toggles a Boolean value |
| `fields/basic/boolean_toggle/` | features | 2 | Toggle switch field widget for Boolean columns |
| `fields/basic/char/` | features | 1 | Single-line text input field for Char columns |
| `fields/basic/color/` | features | 1 | Native color picker input field for Char columns |
| `fields/basic/copy_clipboard/` | features | 1 | Wrapper field that adds a copy-to-clipboard button to Char/URL fields |
| `fields/basic/email/` | features | 1 | Email input field with mailto link in readonly mode |
| `fields/basic/float/` | features | 1 | Numeric input field for Float columns with locale-aware formatting |
| `fields/basic/float_factor/` | features | 1 | Float field that applies a multiplication factor for display and storage |
| `fields/basic/float_time/` | features | 1 | Time duration input that stores hours as a float (e.g. 1.5 = 1h30) |
| `fields/basic/float_toggle/` | features | 1 | Cyclic button that steps through a list of float values on click |
| `fields/basic/html/` | features | 1 | Simple HTML field widget extending TextField for Html columns |
| `fields/basic/integer/` | features | 1 | Numeric input field for Integer columns with locale-aware formatting |
| `fields/basic/json/` | features | 1 | Read-only display field for JSON columns |
| `fields/basic/json_checkboxes/` | features | 1 | Checkbox group field backed by a JSON object of boolean flags |
| `fields/basic/monetary/` | features | 1 | Currency-aware numeric input field for Monetary columns |
| `fields/basic/percentage/` | features | 1 | Numeric input field that displays and parses percentage values |
| `fields/basic/phone/` | features | 1 | Phone number input field with tel: link in readonly mode |
| `fields/basic/text/` | features | 1 | Multi-line textarea input field for Text columns |
| `fields/basic/url/` | features | 1 | URL input field with clickable hyperlink in readonly mode |
| `fields/display/` | features | 0 | Field-widget category (parent): read-only display widgets — see child dirs (badge, gauge, progress_bar, statusbar, …) |
| `fields/display/badge/` | features | 1 | Read-only badge pill for Selection and Many2one columns |
| `fields/display/contact_statistics/` | features | 1 | Read-only contact statistics summary widget |
| `fields/display/gauge/` | features | 1 | Chart.js doughnut gauge visualization for numeric fields |
| `fields/display/handle/` | features | 1 | Drag handle icon for manual record reordering in list views |
| `fields/display/percent_pie/` | features | 1 | Pie chart visualization showing a percentage value |
| `fields/display/progress_bar/` | features | 2 | Kanban-view variant of the progress bar field |
| `fields/display/stat_info/` | features | 1 | Stat button content showing a formatted value with a label |
| `fields/display/statusbar/` | features | 1 | Horizontal pipeline status bar for Selection and Many2one columns |
| `fields/hooks/` | features | 1 | OWL hooks shared across field widgets (e.g. `record_observer.js`). |
| `fields/media/` | features | 0 | Field-widget category (parent): media widgets — see child dirs (binary, image, pdf_viewer, signature, …) |
| `fields/media/attachment_image/` | features | 1 | Read-only image display field for Many2one attachment references |
| `fields/media/binary/` | features | 1 | File upload/download field for Binary columns |
| `fields/media/contact_image/` | features | 1 | Image field variant with fallback to a preview image when empty |
| `fields/media/image/` | features | 2 | Image upload, preview, and zoom field for Binary image columns |
| `fields/media/image_url/` | features | 1 | Image display field that loads from a URL stored in a Char column |
| `fields/media/pdf_viewer/` | features | 1 | Embedded PDF viewer field for Binary columns using PDF.js |
| `fields/media/signature/` | features | 1 | Signature pad field for capturing and storing handwritten signatures |
| `fields/relational/` | features | 5 | Autocomplete component for many2one/many2many fields with search, quick-creat... |
| `fields/relational/many2many_binary/` | features | 1 | File attachment list field for Many2many relations to ir.attachment |
| `fields/relational/many2many_checkboxes/` | features | 1 | Checkbox group field for Many2many relations |
| `fields/relational/many2many_tags/` | features | 2 | Kanban-view variant of Many2many tags showing only colored tags |
| `fields/relational/many2many_tags_avatar/` | features | 1 | Avatar tag list field for Many2many relations with user images |
| `fields/relational/many2one/` | features | 2 | Core Many2One autocomplete component with search, navigation, and barcode sup... |
| `fields/relational/many2one_avatar/` | features | 2 | Kanban-view Many2one field displaying an avatar image |
| `fields/relational/many2one_barcode/` | features | 1 | Many2one field with barcode scanner support |
| `fields/relational/many2one_reference/` | features | 1 | Many2one field for Many2oneReference columns with dynamic relation model |
| `fields/relational/many2one_reference_integer/` | features | 1 | Integer display field for Many2oneReference columns showing the record ID |
| `fields/relational/reference/` | features | 1 | Reference field widget combining a model selector with a Many2one picker |
| `fields/relational/x2many/` | features | 2 | Read-only list-view summary field for One2many and Many2many columns |
| `fields/selection/` | features | 1 | Abstract base class for selection-like fields with special data loading |
| `fields/selection/badge_selection/` | features | 2 | Clickable badge group field for Selection and Many2one columns |
| `fields/selection/badge_selection_with_filter/` | features | 1 | Badge selection field filtered by an allowed-values field |
| `fields/selection/label_selection/` | features | 1 | Colored label display field for Selection columns |
| `fields/selection/priority/` | features | 1 | Star rating field for priority Selection columns |
| `fields/selection/radio/` | features | 1 | Radio button group field for Selection and Many2one columns |
| `fields/selection/selection/` | features | 2 | Selection dropdown field with whitelist/blacklist value filtering |
| `fields/selection/state_selection/` | features | 1 | Kanban-style colored state dot dropdown for Selection columns |
| `fields/specialized/` | features | 0 | Field-widget category (parent): specialized widgets — see child dirs (domain, properties, ace, color_picker, …) |
| `fields/specialized/ace/` | features | 1 | Code editor field using the Ace/CodeEditor component |
| `fields/specialized/color_picker/` | features | 1 | Predefined color palette picker field for Integer columns |
| `fields/specialized/domain/` | features | 1 | Domain expression editor field with record count and selector UI |
| `fields/specialized/field_selector/` | features | 1 | Model field path selector field for Char columns |
| `fields/specialized/google_slide_viewer/` | features | 1 | Embedded Google Slides presentation viewer field |
| `fields/specialized/iframe_wrapper/` | features | 1 | Iframe wrapper that renders HTML field content inside an isolated iframe |
| `fields/specialized/ir_ui_view_ace/` | features | 2 | Ace code-editor field for ir.ui.view XML arch, highlighting invalid XPath locators |
| `fields/specialized/journal_dashboard_graph/` | features | 1 | Chart.js graph field for accounting journal dashboard data |
| `fields/specialized/kanban_color_picker/` | features | 1 | Inline color palette picker for kanban card color selection |
| `fields/specialized/properties/` | features | 10 | Calendar-view read-only variant of the properties field |
| `fields/specialized/properties/icons/` | features | 0 | Property-field type icons (PNG assets) |
| `fields/specialized/user_groups/` | features | 3 | Field widget for visualizing and configuring res.users access rights (group_ids), implication popover, and per-privilege boolean field. |
| `fields/temporal/` | features | 0 | Field-widget category (parent): temporal widgets — see child dirs (datetime, remaining_days, timezone_mismatch) |
| `fields/temporal/datetime/` | features | 2 | Date and datetime field widget with inline editing and picker integration |
| `fields/temporal/remaining_days/` | features | 1 | Deadline countdown field showing remaining days with color-coded urgency |
| `fields/temporal/timezone_mismatch/` | features | 1 | Timezone selection field that warns when browser and user timezones differ |
| `libs/` | misc | 2 | Vendored-in-src glue: Bootstrap entry point and `popper_compat.js` (the in-house positioning shim Bootstrap resolves as `@popperjs/core`) |
| `libs/fontawesome7/` | misc | 0 | Vendored FontAwesome 7 — icon CSS + webfonts |
| `libs/fontawesome7/css/` | misc | 0 | FontAwesome 7 stylesheets |
| `libs/fontawesome7/webfonts/` | misc | 0 | FontAwesome 7 webfont files |
| `model/` | entities | 8 | Model base class + useReactiveModel hook, sample server/coordinator, property field definitions, shared model utilities |
| `model/relational_model/` | entities | 37 | Relational data model: Record/lists/groups, save & validation orchestration, x2many ORM command serialization (CREATE, UPDATE, LINK, SET...) |
| `public/` | pages | 15 | Interaction that detects Caps Lock state and toggles a warning on password in... |
| `search/` | widgets | 15 | CallbackRecorder utility and useSetupAction hook for persisting view state across filters |
| `search/action_menus/` | widgets | 1 | Action/Print dropdown menus for executing server actions on selected records |
| `search/breadcrumbs/` | widgets | 1 | Navigation breadcrumb trail showing the action stack with back-navigation |
| `search/cog_menu/` | widgets | 1 | Combined cog dropdown merging Action, Print, and registry-based menu items |
| `search/control_panel/` | widgets | 1 | Control panel UI with search bar, breadcrumbs, filter/groupby menus (embedded-actions bar extracted to `search/embedded_actions_bar/`) |
| `search/custom_favorite_item/` | widgets | 1 | Dropdown form for saving the current search as a named favorite filter |
| `search/embedded_actions_bar/` | widgets | 1 | Embedded-actions bar (extracted from ControlPanel): renders/reorders the top-bar embedded action tabs, visibility + order persisted via res.users.settings |
| `search/custom_group_by_item/` | widgets | 1 | Dropdown item for selecting a custom field to group by |
| `search/properties_group_by_item/` | widgets | 1 | Group-by dropdown item that lazily loads property definitions for grouping |
| `search/search_bar/` | widgets | 2 | Search bar with autocomplete suggestions, facet display, and keyboard navigation |
| `search/search_bar_menu/` | widgets | 1 | Dropdown menu grouping Filter, Group By, Favorites, and search panels |
| `search/search_panel/` | widgets | 3 | Sidebar filter panel with category trees and grouped checkbox filters |
| `search/utils/` | widgets | 3 | Date period/quarter/interval option definitions and domain generators for sea... |
| `search/with_search/` | widgets | 1 | Wrapper component that creates a SearchModel and injects it into the sub-envi... |
| `services/` | shared | 22 | Top-level data & input singletons: orm, http, field, name, currency, file_upload, sortable, error, title, localization, scss_error_display, frequent_emoji, tree_processor, lazy_session, multi_company_recovery, form_dialog_stack, slow_rpc |
| `services/commands/` | shared | 5 | (generated/vendored — no description) |
| `services/debug/` | shared | 6 | Debug context manager that collects and merges debug menu items by category |
| `services/hotkeys/` | shared | 2 | useHotkey hook to register/unregister keyboard shortcuts with component lifec... |
| `services/install_scoped_app/` | shared | 1 | Public page component for installing scoped Progressive Web Apps |
| `services/navigation/` | shared | 1 | Keyboard arrow-key navigation hook for selectable item lists |
| `services/pwa/` | shared | 2 | Dialog showing Safari-specific PWA installation instructions (iOS and macOS) |
| `services/web_vitals/` | shared | 1 | RUM Phase 1 Core Web Vitals beacon: PerformanceObserver captures LCP/FCP/CLS/TTFB/INP (INP = worst-observed P100 interaction duration) and ships them via `navigator.sendBeacon` to `/web/observability/cwv` on `pagehide`. |
| `ui/` | shared | 2 | `ui_service.js` (active element / block UI) + `viewport.js`; every other UI service lives in a subdirectory: `alert/`, `block/`, `bottom_sheet/`, `carousel/`, `collapse/`, `dialog/`, `effects/`, `notification/`, `offcanvas/`, `overlay/`, `popover/`, `tooltip/`. |
| `ui/alert/` | shared | 1 | Service tracking dismissed alerts so they stay dismissed |
| `ui/block/` | shared | 1 | Full-screen overlay component that blocks UI during long-running operations |
| `ui/bottom_sheet/` | shared | 2 | Mobile-friendly slide-up panel with drag-to-dismiss and snap points |
| `ui/carousel/` | shared | 1 | Hook wrapping Bootstrap's carousel lifecycle for OWL components |
| `ui/collapse/` | shared | 1 | Animated expand/collapse panel component |
| `ui/dialog/` | shared | 3 | Standard confirm/cancel dialog with async button handling |
| `ui/effects/` | shared | 2 | Service that triggers visual effects (rainbow man) via the effects registry |
| `ui/notification/` | shared | 3 | Individual notification toast with auto-close progress bar and action buttons |
| `ui/offcanvas/` | shared | 1 | Slide-in off-canvas panel component |
| `ui/overlay/` | shared | 3 | Renders overlay entries (popovers, dialogs, effects) with nested click-away t... |
| `ui/popover/` | shared | 4 | Positioned popover component with click-away close, hotkey escape, and arrow ... |
| `ui/tooltip/` | shared | 2 | Simple tooltip component rendered by the tooltip service |
| `views/` | widgets | 15 | Empty-state placeholder shown when a view has no records |
| `views/calendar/` | widgets | 8 | Parses calendar view XML arch into field mappings, scales, filters, and popov... |
| `views/calendar/calendar_common/` | widgets | 3 | Popover for calendar events in day/week/month scales |
| `views/calendar/calendar_filter_section/` | widgets | 1 | Collapsible sidebar filter section for a calendar filter field (attendees, re... |
| `views/calendar/calendar_side_panel/` | widgets | 1 | Side panel with date picker and filter sections for the calendar view |
| `views/calendar/calendar_year/` | widgets | 2 | Popover listing grouped records when clicking a day cell in year view |
| `views/calendar/hooks/` | widgets | 3 | Hook managing calendar event popovers with desktop/mobile responsive behavior |
| `views/calendar/mobile_filter_panel/` | widgets | 1 | Compact filter panel for mobile calendar with sidebar toggle |
| `views/calendar/quick_create/` | widgets | 1 | Lightweight dialog for creating a calendar event with just a title |
| `views/form/` | widgets | 9 | Parses form view XML arch into field/widget descriptors, active actions, and ... |
| `views/form/button_box/` | widgets | 1 | Responsive stat-button container with overflow dropdown for form views |
| `views/form/form_cog_menu/` | widgets | 1 | Form-view variant of the cog menu with save-before-action behavior |
| `views/form/form_error_dialog/` | widgets | 1 | Error dialog shown on form save failure with discard/redirect/stay options |
| `views/form/form_group/` | widgets | 1 | OuterGroup and InnerGroup components for form view column layout |
| `views/form/form_status_indicator/` | widgets | 1 | Save/discard indicator shown when the form record is dirty or invalid |
| `views/form/setting/` | widgets | 1 | Individual setting row with label, help text, and company-dependent icon |
| `views/form/status_bar_buttons/` | widgets | 1 | Renders action buttons in the form status bar with overflow dropdown |
| `views/graph/` | widgets | 7 | Parses graph view XML arch into chart mode, measures, groupBy, and display flags |
| `views/kanban/` | widgets | 19 | Kanban view: arch parser, renderer, progress-bar hook with local drag-move reconcile, quick create, ... |
| `views/list/` | widgets | 21 | List view: renderer + per-row `ListRecordRow` component (renderer-delegation contract), column width calculation, keyboard nav/edit, styling |
| `views/list/export_all/` | widgets | 1 | Cog-menu item triggering direct XLSX export of all records |
| `views/pivot/` | widgets | 12 | Parses pivot view XML arch into measures, row/column groupBy, and display flags |
| `views/view_button/` | widgets | 3 | ViewButton variant for list/kanban headers that operates on multiple selected... |
| `views/view_components/` | widgets | 7 | Numeric display with smooth CSS animation on value changes and optional multi... |
| `views/view_dialogs/` | widgets | 3 | Export configuration dialog: field selection, template management, and format... |
| `views/widgets/` | widgets | 2 | Standard OWL prop definitions shared by all view widgets (record and readonly) |
| `views/widgets/attach_document/` | widgets | 1 | Widget button that uploads files as ir.attachment records and optionally call... |
| `views/widgets/documentation_link/` | widgets | 1 | Widget rendering a hyperlink to versioned Odoo documentation |
| `views/widgets/notification_alert/` | widgets | 1 | Widget displaying a warning banner when browser push notifications are blocked |
| `views/widgets/ribbon/` | widgets | 1 | Decorative ribbon on the top-right corner of a form view with configurable la... |
| `views/widgets/signature/` | widgets | 1 | Widget opening a signature drawing dialog and writing the captured image to a... |
| `views/widgets/week_days/` | widgets | 1 | Widget rendering seven day-of-week checkboxes respecting the locale's week st... |
| `webclient/` | pages | 6 | Service that auto-reloads currencies when res.currency records are mutated |
| `webclient/actions/` | pages | 22 | Executes action buttons (type=object/action/special) with RPC, context filter... |
| `webclient/actions/action_executors/` | pages | 5 | Per-action-type executors: one module each for `act_url`, `act_window`, `client`, `close`, `server`, dispatched by the action service |
| `webclient/actions/reports/` | pages | 4 | Client action rendering an HTML report in an iframe with print button and act... |
| `webclient/actions/reports/layout_assets/` | pages | 0 | Report layout SCSS assets |
| `webclient/burger_menu/` | pages | 1 | Fullscreen mobile menu displaying user menu, company switcher, and current ap... |
| `webclient/burger_menu/burger_user_menu/` | pages | 1 | Mobile variant of the user menu shown inside the burger menu overlay |
| `webclient/burger_menu/mobile_switch_company_menu/` | pages | 1 | Mobile company switcher with collapsible toggle for many companies |
| `webclient/clickbot/` | pages | 2 | Automated UI testing bot that clicks through all apps, views, and filters to ... |
| `webclient/debug/` | pages | 2 | Debug menu items for running unit tests, opening views, and toggling technica... |
| `webclient/debug/profiling/` | pages | 4 | Debug menu dropdown item for toggling SQL/trace profiling collectors |
| `webclient/density/` | pages | 2 | Service managing content density (default/compact/condensed) via body CSS cla... |
| `webclient/errors/` | pages | 2 | Error handler converting browser "Failed to fetch" TypeErrors into Connection... |
| `webclient/loading_indicator/` | pages | 1 | Loading indicator counting active RPCs and blocking the UI after a 3s delay |
| `webclient/menus/` | pages | 4 | Utility functions to traverse the menu tree and compute flat app/menuItem lis... |
| `webclient/navbar/` | pages | 1 | Main navigation bar with app switcher, sub-menus, systray items, and mobile s... |
| `views/settings/` | pages | 5 | Three-way dialog (Save/Discard/Stay) for unsaved settings changes. |
| `views/settings/fields/` | pages | 2 | Boolean field for settings that shows an Enterprise upgrade dialog when checked |
| `views/settings/fields/settings_binary_field/` | pages | 1 | BinaryField variant resolving download URLs via the related field's relation |
| `views/settings/highlight_text/` | pages | 3 | FormLabel variant with search-term highlighting and enterprise upgrade badge |
| `views/settings/settings/` | pages | 5 | Setting variant with search-based visibility filtering and URL hash highlighting |
| `views/settings/widgets/` | pages | 5 | Service that checks whether demo data is active in the current database |
| `webclient/share_target/` | pages | 1 | Service receiving shared files from the PWA service worker (Web Share Target ... |
| `webclient/switch_company_menu/` | pages | 3 | Single company row in the switch-company dropdown with toggle and log-into ac... |
| `webclient/user_menu/` | pages | 2 | Systray dropdown displaying current user avatar and menu items from the user_... |
| `(root)` | misc | 4 | Top-level entry points and session |
| `@types/` | misc | 0 | TypeScript ambient type declarations (`.d.ts`): env, context, fields, models, registries, services, views, owl, user |
| `@types/models/` | misc | 0 | Model-layer ambient types (`_runtime.d.ts`) |
| `@types/registries/` | misc | 0 | Registry ambient types (fields, services, views, command, debug, view_widgets) |
| `scss/` | misc | 0 | Shared SCSS stylesheets (variables, mixins, base backend styles) — ~197 `.scss`, no JS |
