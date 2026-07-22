/** @odoo-module native */

/**
 * Access to the Bootstrap components of the *edited document's* JS realm.
 *
 * Builder plugins execute in the backend window but act on elements that live
 * inside the preview iframe. That distinction is load-bearing for Bootstrap:
 * its components read the ambient `document` of the realm their class was
 * defined in, and `Modal` goes as far as relocating its own element —
 *
 *     if (!document.body.contains(this._element)) document.body.append(...)
 *
 * — so driving an iframe element with the *backend* realm's class silently
 * moves the popup out of the editable and into the backend body. Importing
 * `@web/libs/bootstrap` here would give exactly that wrong class; the one to
 * use is published by the edited document itself, in
 * `core/website_edit_service.js` (`__odooWebsiteEditBootstrap`).
 *
 * Historically these call sites read `iframeWindow.Modal`, back when Bootstrap
 * was a set of globals. It is now an ES module bundle that exposes nothing on
 * `window`, so those reads silently became `undefined` and their callers threw
 * "Cannot read properties of undefined" — which is what this indirection fixes.
 *
 * @param {Window} win the edited document's window (a plugin's `this.window`)
 * @param {string} name the component name, e.g. "Modal" or "Tab"
 * @returns {Function|undefined} the component class, or undefined when the
 *      edit-mode bundle is not loaded in that realm (some editor tests mount
 *      without it, so callers must degrade rather than throw)
 */
export function getBootstrapComponent(win, name) {
    return win?.__odooWebsiteEditBootstrap?.[name];
}
