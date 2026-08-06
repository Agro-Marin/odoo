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
 * The same surface as a type, for executors declaring what they ask of the
 * manager rather than taking the whole class.
 *
 * `_loadStateGeneration` is deliberately absent: it is a counter
 * `load_state.js` reads to detect a superseded navigation, which is state
 * rather than an operation, and the one place it is stubbed is testing exactly
 * that supersession. It stays undeclared so it keeps showing up as debt — the
 * question "should navigation generation be `load_state`'s own?" has not been
 * answered, and declaring it would retire the question rather than settle it.
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
