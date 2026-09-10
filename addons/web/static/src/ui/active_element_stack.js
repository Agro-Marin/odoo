// @ts-check
/** @odoo-module native */

/**
 * @returns {{
 * current: Document | HTMLElement,
 * activate(el: HTMLElement): void,
 * deactivate(el: HTMLElement): boolean,
 * activeElementOf(node: Node): Document | HTMLElement | undefined,
 * scopeOf(node: Node | null): Document | HTMLElement,
 * reset(): void,
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

        /** @returns {boolean} */
        deactivate(el) {
            const index = stack.lastIndexOf(el);
            if (index === -1) {
                return false;
            }
            stack.splice(index, 1);
            return true;
        },

        activeElementOf(node) {
            for (let i = stack.length - 1; i >= 0; i--) {
                if (stack[i].contains(node)) {
                    return stack[i];
                }
            }
        },

        scopeOf(node) {
            return (
                (node && this.activeElementOf(node)) ||
                /** @type {Document | HTMLElement} */ (stack[0])
            );
        },

        reset() {
            stack = [document];
        },
    };
}
