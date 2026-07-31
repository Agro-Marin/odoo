// @ts-check
/** @odoo-module native */

/** @module @web/ui/dialog/dialog_service */

import { Component, markRaw, reactive, useChildSubEnv, xml } from "@odoo/owl";
import { registry } from "@web/core/registry";

registry
    .category("dialogs")
    .addValidation((entry) => entry?.prototype instanceof Component);

class DialogWrapper extends Component {
    static template = xml`<t t-component="props.subComponent" t-props="props.subProps" />`;
    static props = {
        subComponent: Function,
        subProps: Object,
        subEnv: Object,
    };
    setup() {
        useChildSubEnv({ dialogData: this.props.subEnv });
    }
}

/**
 * @typedef {{
 *      onClose?(closeParams?: any): void;
 *      env?: object;
 *      rootId?: string;
 *  }} DialogServiceInterfaceAddOptions
 */
/**
 * @typedef {{
 *      add(
 *          Component: import("@odoo/owl").ComponentConstructor,
 *          props?: {},
 *          options?: DialogServiceInterfaceAddOptions
 *      ): () => void;
 *      closeAll(params?: any): void;
 *      destroy(): void;
 *  }} DialogServiceInterface
 */

export const dialogService = {
    dependencies: ["overlay"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ overlay: any }} services
     * @returns {DialogServiceInterface}
     */
    start(env, { overlay }) {
        /**
         * @type {Array<{ id: number, close: Function, isActive: boolean, scrollToOrigin?: () => void }>}
         */
        const stack = [];
        let nextId = 0;
        /**
         * @type {{ top: number, left: number } | null}
         */
        let scrollOrigin = null;

        const deactivate = () => {
            for (const subEnv of stack) {
                subEnv.isActive = false;
            }
        };

        const add = (
            /** @type {import("@odoo/owl").ComponentConstructor} */ dialogClass,
            /** @type {any} */ props,
            /** @type {any} */ options = {},
        ) => {
            const id = nextId++;
            const close = (/** @type {any} */ params) => {
                subEnv.isClosing = true;
                return remove(params);
            };
            const subEnv = reactive(
                /**
                 * @type {{ id: number, close: Function, isActive: boolean, isClosing: boolean, scrollToOrigin?: () => void }}
                 */ ({
                    id,
                    close,
                    isActive: true,
                    isClosing: false,
                }),
            );

            if (!stack.length) {
                scrollOrigin = { top: window.scrollY, left: window.scrollX };
            }
            deactivate();
            stack.push(subEnv);
            document.body.classList.add("modal-open");

            subEnv.scrollToOrigin = () => {
                if (!stack.length && scrollOrigin) {
                    window.scrollTo(scrollOrigin);
                    scrollOrigin = null;
                }
            };

            const remove = overlay.add(
                DialogWrapper,
                {
                    subComponent: dialogClass,
                    subProps: markRaw({ ...props, close }),
                    subEnv,
                },
                {
                    env: options.env,
                    onRemove: async (/** @type {any} */ closeParams) => {
                        try {
                            await options.onClose?.(closeParams);
                        } finally {
                            const idx = stack.findIndex((d) => d.id === id);
                            if (idx !== -1) {
                                stack.splice(idx, 1);
                            }
                            subEnv.isClosing = false;
                            deactivate();
                            if (stack.length) {
                                /** @type {{ isActive: boolean }} */ (
                                    stack.at(-1)
                                ).isActive = true;
                            } else {
                                document.body.classList.remove("modal-open");
                            }
                        }
                    },
                    rootId: options.rootId,
                },
            );

            return remove;
        };

        function closeAll(/** @type {any} */ params) {
            for (const dialog of stack.toReversed()) {
                dialog.close(params);
            }
        }

        return {
            add,
            closeAll,
            destroy() {
                stack.length = 0;
                scrollOrigin = null;
                document.body.classList.remove("modal-open");
            },
        };
    },
};

registry.category("services").add("dialog", dialogService);
