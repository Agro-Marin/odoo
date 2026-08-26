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
 * `website/core/website_edit_service.js` (`__odooWebsiteEditBootstrap`).
 *
 * A second reason not to import it: `web/static/src/libs/bootstrap.js` is not
 * in `web.assets_backend` (it was retired from it), nor in any builder bundle,
 * so the bare specifier resolves to `undefined` rather than failing to load.
 * Every such import is a `TypeError` waiting for its first call site.
 *
 * Lives in `html_builder` rather than `website` because the plugins that need
 * it do: `website` depends on `html_builder`, not the reverse. Realms that
 * publish no bundle (mass_mailing's editor, some editor tests) simply yield
 * `undefined`, so callers must degrade rather than throw.
 *
 * @param {Window} win the edited document's window (a plugin's `this.window`,
 *      or `el.ownerDocument.defaultView` for a given element)
 * @param {string} name the component name, e.g. "Modal" or "Tab"
 * @returns {Function|undefined} the component class, or undefined when the
 *      edit-mode bundle is not loaded in that realm
 */
export function getBootstrapComponent(win, name) {
    return win?.__odooWebsiteEditBootstrap?.[name];
}
