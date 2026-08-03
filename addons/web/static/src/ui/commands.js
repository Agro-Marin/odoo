// @ts-check
/** @odoo-module native */

/** @module @web/ui/commands */

/**
 * The commands module's published interface.
 *
 * Everything under `ui/commands/` that another addon imports today is re-exported here,
 * and nothing else. The names below are the contract; the 4 files behind them
 * are not, and may be renamed, split or moved without touching a
 * consumer OUTSIDE `web`. Inside it they are imported directly and a
 * rename does reach them — the face constrains other addons, which is
 * the only direction `js_face_boundary` enforces.
 *
 * Descriptive rather than aspirational: a face invented ahead of demand is a
 * guess. A consumer needing something not listed adds it here — one visible,
 * reviewable edit instead of a reach into a file.
 *
 * A face is a SIBLING file, not `commands/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/ui/commands` to
 * `/web/static/src/ui/commands.js` by appending `.js`, with no directory-index step.
 */

export { useCommand } from "./commands/command_hook.js";
export { CommandPalette, DefaultCommandItem } from "./commands/command_palette.js";
export { commandService } from "./commands/command_service.js";
export { HotkeyCommandItem } from "./commands/default_providers.js";
