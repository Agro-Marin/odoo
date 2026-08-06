// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_service_contract */

/**
 * What an action executor may ask of the `ActionManager` that drives it.
 *
 * THIS CONTRACT EXISTS BECAUSE A PREVIOUS READING WAS WRONG. The audit ledger's
 * F9 observed that 9 of the 14 privates `ActionManager` exposes to its
 * satellites are one-line forwards to *other* satellites — `_makeController`
 * returns `makeController(params, this)`, `_loadAction` forwards without even
 * passing `this` — and concluded the manager was a switchboard whose hops
 * should be deleted, the satellites importing those functions directly.
 *
 * Measured against the test suite, that is wrong for **all fourteen**. Every one
 * is stubbed by at least one test and several by many:
 *
 *     _controllersFromState  9    _getView       5    _confirmLeave   4
 *     _getActionParams       6    _executeCloseAction 4  _makeController 4
 *     _loadAction            6    _getBreadcrumbs 3    _updateUI       3
 *     _getActionInfo         2    _nextId         2    _removeDialog   1
 *     _getViewInfo           1    _loadStateGeneration 1
 *
 * The forwarding is what makes them substitutable, and substitutable is what an
 * executor needs to be tested without a live manager. A one-line body says the
 * manager delegates; it does not say the delegation is pointless. The same
 * correction was reached twice in the model layer — `record_savepoint`'s three
 * functions and `record._processProperties` both look deletable and are both
 * seams — so the rule is now stated plainly: *the body identifies a candidate,
 * the tests decide it.*
 *
 * So the 14 are declared rather than deleted, and this file is what F9 should
 * have proposed.
 *
 * @type {string[]}
 */
export const ACTION_MANAGER_SURFACE = [
    // public shape a satellite reads or drives
    "breadcrumbCache",
    "controllerStack",
    "dialog",
    "doAction",
    "doActionButton",
    "env",
    "navigation",
    "nextDialog",
    "pushState",
    "restore",
    "router",
    "switchView",
    // operations a satellite invokes, each substitutable by a test
    "_confirmLeave",
    "_controllersFromState",
    "_executeCloseAction",
    "_getActionInfo",
    "_getActionParams",
    "_getBreadcrumbs",
    "_getView",
    "_getViewInfo",
    "_loadAction",
    "_makeController",
    "_nextId",
    "_removeDialog",
    "_updateUI",
];

/**
 * SUPERSESSION, for executors: there is ONE navigation clock — `navigation`,
 * a `NavigationTracker` (see `navigation_token.js`). Every navigation entry
 * point (`doAction` / `switchView` / `restore` / `loadState`) mints an epoch
 * on it; an executor awaiting something on a navigation's behalf goes through
 * `navigation.guard(promise)` (or a token's `settle`) and a stage checking
 * "has a newer navigation started?" asks a token's `isCurrent()` /
 * `throwIfSuperseded()`. The one cancellation outcome, at every stage, is
 * `SupersededError`. Two waits deliberately sit on a different SENSOR while
 * speaking that same error, because their question is "was my container
 * taken?" rather than "was a newer navigation minted?" (a dialog navigation
 * mints but takes no container): the skeleton wait
 * (`ActionManager._awaitSkeletonMount`, cancelled by the next
 * ACTION_MANAGER:UPDATE) and the controller mount
 * (`ActionDispatch.discard()`, cancelled by the container destroying the
 * superseded component). Historical racers are pinned in
 * `navigation_supersession.test.js`; do not add a stage-local counter,
 * generation, or KeepLast — extend the token instead.
 */

/**
 * The same surface as a type, for executors declaring what they ask of the
 * manager rather than taking the whole class.
 *
 * An earlier revision kept `_loadStateGeneration` deliberately absent so the
 * question "should navigation generation be `load_state`'s own?" stayed open.
 * It is now answered: the generation was never `load_state`'s — it is the
 * whole pipeline's, and it lives in `navigation` (a `NavigationTracker`),
 * declared above. `load_state` mints on that clock like every other
 * navigation entry point, and the counter it used to read is gone.
 *
 * `ACTION_MANAGER_SURFACE` and this typedef must name the same members;
 * `tooling/architecture/test_record_contract_agreement.py` checks that.
 *
 * @typedef {{
 *  breadcrumbCache: any,
 *  controllerStack: any[],
 *  dialog: any,
 *  doAction: (request: any, options?: any) => Promise<any>,
 *  doActionButton: (params: any, options?: any) => Promise<any>,
 *  env: any,
 *  navigation: import("./navigation_token.js").NavigationTracker,
 *  nextDialog: any,
 *  pushState: (stack?: any[], options?: any) => void,
 *  restore: (jsId: string) => Promise<any>,
 *  router: any,
 *  switchView: (viewType: string, props?: any, options?: any) => Promise<any>,
 *  _confirmLeave: (options?: any) => Promise<boolean>,
 *  _controllersFromState: (state: any) => Promise<any>,
 *  _executeCloseAction: (action?: any, options?: any) => any,
 *  _getActionInfo: (action: any, props: any) => any,
 *  _getActionParams: (state: any) => any,
 *  _getBreadcrumbs: (stack: any[]) => any,
 *  _getView: (viewType: string) => any,
 *  _getViewInfo: (view: any, action: any, views: any[], props?: any) => any,
 *  _loadAction: (request: any, context?: any) => Promise<any>,
 *  _makeController: (params: any) => any,
 *  _nextId: () => number,
 *  _removeDialog: (closeParams?: any, removeFn?: any) => Promise<any>,
 *  _updateUI: (controller: any, options?: any) => Promise<any>,
 * }} ActionManagerContract
 */
