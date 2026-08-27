// @ts-check
/** @odoo-module native */

import { Component, markRaw, reactive, useChildSubEnv, xml } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { warnUnknownOptions } from "@web/ui/overlay/presenter";

const DIALOG_OPTIONS = new Set(["env", "onClose", "rootId", "sequence"]);

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
 * onClose?(closeParams?: any): void;
 * env?: object;
 * rootId?: string;
 * sequence?: number;
 * }} DialogServiceInterfaceAddOptions
 */
/**
 * @typedef {{
 * add(
 * Component: import("@odoo/owl").ComponentConstructor,
 * props?: Record<string, any>,
 * options?: DialogServiceInterfaceAddOptions
 * ): (closeParams?: any) => Promise<void>;
 * closeAll(params?: any): Promise<void>;
 * destroy(): void;
 * }} DialogServiceInterface
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
     * @param {import("@odoo/owl").ComponentConstructor} dialogClass
     * @param {Record<string, any>} [props]
     * @param {DialogServiceInterfaceAddOptions} [options]
     * @returns {(closeParams?: any) => Promise<void>}
     */
    add(dialogClass, props, options = {}) {
        warnUnknownOptions("dialog", options, DIALOG_OPTIONS);
        const id = this.nextId++;
        const close = (/** @type {any} */ params) => {
            subEnv.isClosing = true;
            return remove(params);
        };
        const subEnv = reactive(
            /** @type {{ id: number, close: Function, isActive: boolean, isClosing: boolean, scrollToOrigin?: () => void }} */ ({
                id,
                close,
                isActive: true,
                isClosing: false,
            }),
        );

        if (!this.stack.length) {
            this.scrollOrigin = { top: browser.scrollY, left: browser.scrollX };
        }
        this.deactivate();
        this.stack.push(subEnv);
        document.body.classList.add("modal-open");

        subEnv.scrollToOrigin = () => {
            if (!this.stack.length && this.scrollOrigin) {
                browser.scrollTo(this.scrollOrigin);
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
                sequence: options.sequence,
            },
        );

        return close;
    }

    /**
     * @param {any} [params]
     * @returns {Promise<void>}
     */
    async closeAll(params) {
        await Promise.all(
            this.stack.toReversed().map((dialog) => dialog.close(params)),
        );
    }

    destroy() {
        this.closeAll().catch(() => {});
        this.stack.length = 0;
        this.nextId = 0;
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
