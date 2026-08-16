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
 *          props?: Record<string, any>,
 *          options?: DialogServiceInterfaceAddOptions
 *      ): () => void;
 *      closeAll(params?: any): Promise<void>;
 *      destroy(): void;
 *  }} DialogServiceInterface
 */

/**
 * The `dialog` service.
 *
 * A class rather than a closure returning an object literal; see
 * `core/hotkeys/hotkey_service.js` for the reasoning and
 * `tooling/architecture/js_service_shape.py` for the budget.
 *
 * `destroy()` calls `this.closeAll()` — the prototype form of the facade
 * routing `js_patch_blind_facade` added here, so a downstream patch of
 * `closeAll` still applies when the service tears itself down.
 *
 * Everything inside `add()` stays local to `add()`: `id`, `close`, `subEnv` and
 * `remove` all belong to one dialog, not to the service, and the overlay's
 * `onRemove` closes over exactly that dialog's identity.
 */
export class DialogService {
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ overlay: any }} services
     */
    constructor(env, { overlay }) {
        this.env = env;
        this.overlay = overlay;
        /**
         * @type {Array<{ id: number, close: Function, isActive: boolean, scrollToOrigin?: () => void }>}
         */
        this.stack = [];
        this.nextId = 0;
        /**
         * @type {{ top: number, left: number } | null}
         */
        this.scrollOrigin = null;
    }

    deactivate() {
        for (const subEnv of this.stack) {
            subEnv.isActive = false;
        }
    }

    /**
     * Typed as precisely as the `DialogServiceInterface` typedef this class
     * replaced. Writing `options: any` here instead made 19 tsc errors
     * disappear — not because anything was fixed, but because every consumer
     * passing an option outside `{ onClose, env, rootId }` stopped being
     * checked. A conversion must not buy a smaller number with a weaker
     * contract; that is the same fault as `loadDisplayNames: Function`, pointed
     * the other way.
     *
     * `props` is `Record<string, any>` and NOT `{}`: `{}` accepts every
     * non-null value at a call site, so it never checked what a caller passed,
     * while forbidding every read of a property on it. Mocks and patches of
     * this method have to read the props they were handed. Widening it costs no
     * call-site checking, unlike `options` above.
     *
     * @param {import("@odoo/owl").ComponentConstructor} dialogClass
     * @param {Record<string, any>} [props]
     * @param {DialogServiceInterfaceAddOptions} [options]
     * @returns {() => void}
     */
    add(dialogClass, props, options = {}) {
        const id = this.nextId++;
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

        if (!this.stack.length) {
            this.scrollOrigin = { top: window.scrollY, left: window.scrollX };
        }
        this.deactivate();
        this.stack.push(subEnv);
        document.body.classList.add("modal-open");

        subEnv.scrollToOrigin = () => {
            if (!this.stack.length && this.scrollOrigin) {
                window.scrollTo(this.scrollOrigin);
                this.scrollOrigin = null;
            }
        };

        const remove = this.overlay.add(
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
                        const idx = this.stack.findIndex((d) => d.id === id);
                        if (idx !== -1) {
                            this.stack.splice(idx, 1);
                        }
                        subEnv.isClosing = false;
                        this.deactivate();
                        if (this.stack.length) {
                            /** @type {{ isActive: boolean }} */ (
                                this.stack.at(-1)
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
    }

    /**
     * @param {any} [params]
     * @returns {Promise<void>} settles once every dialog has actually gone
     */
    async closeAll(params) {
        await Promise.all(
            this.stack.toReversed().map((dialog) => dialog.close(params)),
        );
    }

    destroy() {
        // Through `closeAll`, so a caller's `onClose` still runs and the
        // dialogs actually leave the screen. Dropping the stack alone
        // left whoever called `destroy()` directly with a modal still
        // mounted and a service that believed nothing was open; on the
        // usual path it only looked right because `overlay` is a
        // dependency, hence destroyed first, and tore them down itself.
        // Swallowed for the reason `overlayService.destroy` gives: at
        // teardown there is no caller left to hand a rejection to.
        // Routed through `this` so a downstream patch of `closeAll` applies.
        this.closeAll().catch(() => {});
        this.stack.length = 0;
        this.scrollOrigin = null;
        document.body.classList.remove("modal-open");
    }
}

export const dialogService = {
    dependencies: ["overlay"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ overlay: any }} services
     * @returns {DialogService}
     */
    start(env, services) {
        return new DialogService(env, services);
    },
};

registry.category("services").add("dialog", dialogService);
