// @ts-check
/** @odoo-module native */

/** @module @web/ui/active_element_stack */

/**
 * The stack of elements that have claimed the UI, innermost last. `document` is
 * the floor and is never popped.
 *
 * A multiset, not a set: `activate` is public and callers drive it from focus
 * events, so the same element can legitimately be pushed more than once --
 * knowledge's embedded view re-activates its host whenever the active element
 * stops being inside it, which an overlay stacked on top makes true. `deactivate`
 * therefore drops one occurrence, the last, so an activation that is still
 * outstanding survives its sibling being released.
 *
 * @returns {{
 *   current: Document | HTMLElement,
 *   activate(el: HTMLElement): void,
 *   deactivate(el: HTMLElement): boolean,
 *   activeElementOf(node: Node): Document | HTMLElement | undefined,
 *   reset(): void,
 * }}
 */
export function makeActiveElementStack() {
    /** @type {(Document | HTMLElement)[]} */
    let stack = [document];

    return {
        get current() {
            return /** @type {Document | HTMLElement} */ (stack.at(-1));
        },

        activate(el) {
            stack.push(el);
        },

        /** @returns {boolean} whether the element was on the stack at all */
        deactivate(el) {
            const index = stack.lastIndexOf(el);
            if (index === -1) {
                return false;
            }
            stack.splice(index, 1);
            return true;
        },

        /** The innermost active element containing `node`, if any. */
        activeElementOf(node) {
            for (let i = stack.length - 1; i >= 0; i--) {
                if (stack[i].contains(node)) {
                    return stack[i];
                }
            }
        },

        reset() {
            stack = [document];
        },
    };
}
