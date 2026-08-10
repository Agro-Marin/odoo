// @ts-check
/** @odoo-module native */

/** @module @web/views/view_config */

/**
 * The keys `web` puts in `env.config`, and therefore owns.
 *
 * `env.config` is the bag every view and every control-panel component reads
 * through `this.env.config.<key>`. Until this file, nothing stated its shape.
 * `getDefaultConfig()` seeds fifteen keys and reads like the declaration, but it
 * is one of **five** writers in this addon alone:
 *
 * | Writer | Adds |
 * |---|---|
 * | `views/view.js` `getDefaultConfig()` | the fifteen seeds |
 * | `views/view.js` `View.loadView()` | `rawArch`, `viewArch`, `viewId`, `viewType`, `viewSubType`, `noBreadcrumbs`, and whatever `extractLayoutComponents` returns (`ControlPanel`, `SearchPanel`) |
 * | `webclient/actions/action_info_builders.js` | ten keys for an act_window, two for a client action |
 * | `webclient/actions/action_service.js` | `breadcrumbs`, `getDisplayName`, `setDisplayName`, `historyBack`, `isReloadingController` |
 * | `webclient/actions/blank_component.js` | `breadcrumbs`, `noBreadcrumbs` |
 *
 * `loadView` writes by `Object.assign` onto the live sub-env object, so the
 * shape a component sees depends on how far the view got. The bag is a plain
 * object, not a reactive one — only `breadcrumbs` inside it is reactive — so a
 * key written after a reader's render does not notify anybody; correctness
 * rests on `loadView` being awaited before the render, not on subscription.
 *
 * Listing the keys does not make the bag good design. It makes the bag
 * *stated*, which is the precondition for narrowing it: `js_env_config_surface`
 * pins who reaches which key, so a removal is a decision someone takes rather
 * than a breakage someone discovers.
 *
 * @type {string[]}
 */
export const VIEW_CONFIG_SURFACE = [
    // the action this view belongs to
    "actionId",
    "actionName",
    "actionType",
    "actionXmlId",
    "cache",
    // breadcrumbs and the display name shown in them
    "breadcrumbs",
    "getDisplayName",
    "setDisplayName",
    "historyBack",
    "noBreadcrumbs",
    // embedded actions
    "embeddedActions",
    "currentEmbeddedActionId",
    "parentActionId",
    // the view itself
    "rawArch",
    "viewArch",
    "viewId",
    "viewType",
    "viewSubType",
    "views",
    "viewSwitcherEntries",
    // layout, injected by `extractLayoutComponents` (`@web/search/layout`)
    "ControlPanel",
    "SearchPanel",
    // control-panel behaviour
    "disableSearchBarAutofocus",
    "pagerProps",
    // set by `action_service` around a reload so `view_utils` can tell an
    // in-flight controller swap from a fresh mount
    "isReloadingController",
];

/**
 * Keys that addons **outside** `web` store in `env.config`.
 *
 * Recorded, not blessed. `env.config` is reachable from every component in the
 * tree, so an addon needing per-action state of its own can reach for it
 * instead of holding that state itself — and nothing stops it, because the bag
 * has no declared shape and `js_extension_surface` cannot see it (a key is
 * neither a class member nor an import).
 *
 * The two live instances:
 *
 * - `enterprise/mrp_mps` **writes** `offset` and `limit` here and reads them
 *   back, using web's ambient object as its own pager state.
 * - `enterprise/web_studio` calls `env.config.onNodeClicked(xpath)` from eleven
 *   sites, and its `form_editor_compiler` interpolates
 *   `__comp__.env.config.onNodeClicked` straight into generated template source
 *   — so the key is load-bearing inside compiled QWeb, where no static check in
 *   this repo can follow it.
 *
 * Neither is web's to delete, and neither should be quietly promoted into
 * `VIEW_CONFIG_SURFACE`: that would make web responsible for state it does not
 * set. Naming them separately keeps the distinction that matters — web's own
 * keys are a contract web maintains, these are squatters web knows about.
 *
 * @type {string[]}
 */
export const VIEW_CONFIG_FOREIGN_SURFACE = ["limit", "offset", "onNodeClicked"];

/**
 * The owned surface as a type.
 *
 * `VIEW_CONFIG_SURFACE` and this typedef must name the same keys; they are
 * checked against each other in `view_config.test.js`, which also checks the
 * array against what `getDefaultConfig()` actually returns.
 *
 * Deliberately not a closed type for consumers to assert against: `env.config`
 * genuinely carries foreign keys (above), and a type claiming otherwise would
 * be a lie that `@ts-check` would then enforce against honest code.
 *
 * @typedef {{
 *  actionId: number | false,
 *  actionName?: string,
 *  actionType: string | false,
 *  actionXmlId?: string | false,
 *  cache?: boolean,
 *  breadcrumbs: { name?: string, [key: string]: any }[],
 *  getDisplayName: () => string,
 *  setDisplayName: (displayName: string) => void,
 *  historyBack: () => void,
 *  noBreadcrumbs?: boolean,
 *  embeddedActions: any[],
 *  currentEmbeddedActionId: number | false,
 *  parentActionId: number | false,
 *  rawArch?: string,
 *  viewArch?: Element,
 *  viewId?: number | false,
 *  viewType?: string,
 *  viewSubType?: string,
 *  views: any[],
 *  viewSwitcherEntries: { type: string, [key: string]: any }[],
 *  ControlPanel?: any,
 *  SearchPanel?: any,
 *  disableSearchBarAutofocus: boolean,
 *  pagerProps: Record<string, any>,
 *  isReloadingController?: boolean,
 * }} ViewConfig
 */
