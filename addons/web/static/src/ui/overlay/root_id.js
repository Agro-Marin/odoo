// @ts-check
/** @odoo-module native */

/**
 * The id of the shadow host a node lives under, or undefined in the main
 * document.
 *
 * An overlay is rendered by the `OverlayContainer` whose `rootId` matches its
 * own, so this is what routes a popover, a dropdown or a dialog into the app it
 * was opened from rather than into the page behind it. Every caller that owns a
 * DOM node -- the target of a popover, the root of the component opening a
 * dialog -- derives it the same way.
 *
 * @param {Node | null | undefined} node
 * @returns {string | undefined}
 */
export function rootIdOf(node) {
    return /** @type {ShadowRoot | undefined} */ (node?.getRootNode())?.host?.id;
}
