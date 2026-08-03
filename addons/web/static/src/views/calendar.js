// @ts-check
/** @odoo-module native */

/** @module @web/views/calendar */

/**
 * The calendar module's published interface.
 *
 * Everything under `views/calendar/` that another addon imports today is re-exported here,
 * and nothing else. The names below are the contract; the 13 files behind them
 * are not, and may be renamed, split or moved without touching a
 * consumer OUTSIDE `web`. Inside it they are imported directly and a
 * rename does reach them — the face constrains other addons, which is
 * the only direction `js_face_boundary` enforces.
 *
 * Descriptive rather than aspirational: a face invented ahead of demand is a
 * guess. A consumer needing something not listed adds it here — one visible,
 * reviewable edit instead of a reach into a file.
 *
 * A face is a SIBLING file, not `calendar/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/views/calendar` to
 * `/web/static/src/views/calendar.js` by appending `.js`, with no directory-index step.
 */

export { CalendarCommonPopover } from "./calendar/calendar_common/calendar_common_popover.js";
export { CalendarCommonRenderer } from "./calendar/calendar_common/calendar_common_renderer.js";
export { CalendarController, SCALE_LABELS } from "./calendar/calendar_controller.js";
export { CalendarFilterSection } from "./calendar/calendar_filter_section/calendar_filter_section.js";
export { CalendarModel } from "./calendar/calendar_model.js";
export { CalendarRenderer } from "./calendar/calendar_renderer.js";
export { CalendarSidePanel } from "./calendar/calendar_side_panel/calendar_side_panel.js";
export { convertRecordToEvent, getColor } from "./calendar/calendar_utils.js";
export { calendarView } from "./calendar/calendar_view.js";
export { CalendarYearPopover } from "./calendar/calendar_year/calendar_year_popover.js";
export { CalendarYearRenderer } from "./calendar/calendar_year/calendar_year_renderer.js";
export { useCalendarPopover } from "./calendar/hooks/calendar_popover_hook.js";
export { CalendarMobileFilterPanel } from "./calendar/mobile_filter_panel/calendar_mobile_filter_panel.js";
