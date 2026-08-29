/** @odoo-module native */
import { App } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { getTemplate } from "@web/core/templates";
import { appTranslateFn } from "@web/core/translation";
const DEFAULT_ID = Symbol("default");

/**
 * @typedef {{ externalWindow: Window|null, generation: number, hooks: { beforePopout?: Function, afterPopoutClosed?: Function }, app?: App }} Popout
 */

class MailPopout {
    /** @type {Map<any, Popout>} */
    popouts = new Map();

    /** @param {import("@web/env").OdooEnv} env */
    constructor(env) {
        this.env = env;
        browser.addEventListener("beforeunload", () => this.closeAll());
    }

    closeAll() {
        for (const popout of this.popouts.values()) {
            const externalWindow = popout.externalWindow;
            if (externalWindow && !externalWindow.closed) {
                externalWindow.close();
            }
        }
    }

    /**
     * @param {any} id
     * @param {Object} [options]
     * @param {Boolean} [options.useAlternativeAssets]
     */
    async reset(id, { useAlternativeAssets } = {}) {
        const popout = this.popouts.get(id);
        if (!popout) {
            return;
        }
        const doc = popout.externalWindow?.document;
        if (doc) {
            doc.head.textContent = "";
            if (useAlternativeAssets) {
                await mailPopoutService.addAssets(popout.externalWindow);
            } else {
                doc.write(window.document.head.outerHTML);
            }
            doc.body = doc.createElement("body");
        }
        if (popout.app) {
            popout.app.destroy();
            popout.app = null;
        }
    }

    /**
     * @param {any} id
     * @param {number} generation
     */
    async pollClosedWindow(id, generation) {
        while (
            this.popouts.get(id)?.externalWindow &&
            this.popouts.get(id).generation === generation
        ) {
            const popout = this.popouts.get(id);
            await new Promise((r) => browser.setTimeout(r, 1000));
            if (popout.generation !== generation) {
                return;
            }
            if (popout.externalWindow?.closed) {
                const hooks = popout.hooks;
                hooks?.afterPopoutClosed?.();
                popout.externalWindow = null;
                await this.reset(id);
            }
        }
    }

    /**
     * @param {any} id
     * @param {number} [width]
     * @param {number} [height]
     * @param {number} [aspectRatio]
     * @returns {Promise<Window>}
     */
    async _openPipWindow(id, width, height, aspectRatio) {
        const popout = this.popouts.get(id);
        popout.hooks?.beforePopout?.();
        height =
            height ||
            (width ? width / aspectRatio : Math.min(240, browser.innerHeight));
        width = width || height * aspectRatio;
        const externalWindow = window.documentPictureInPicture
            ? await window.documentPictureInPicture.requestWindow({ width, height })
            : browser.open(
                  "about:blank",
                  "_blank",
                  `popup=yes,width=${width},height=${height}`,
              );
        this._track(id, externalWindow);
        return externalWindow;
    }

    /**
     * @param {any} id
     * @param {Window} externalWindow
     */
    _track(id, externalWindow) {
        const popout = this.popouts.get(id);
        popout.externalWindow = externalWindow;
        popout.generation++;
        this.pollClosedWindow(id, popout.generation);
    }

    /**
     * @param {any} id
     * @param {typeof import("@odoo/owl").Component} component
     * @param {Object} [props]
     * @param {import("@web/env").OdooEnv} [env]
     */
    _mount(id, component, props, env = this.env) {
        const popout = this.popouts.get(id);
        popout.app = new App(component, {
            name: "Popout",
            env,
            props,
            getTemplate,
            translatableAttributes: ["data-tooltip"],
            translateFn: appTranslateFn,
        });
        popout.app.mount(popout.externalWindow.document.body);
    }

    /**
     * @param {Object} param2
     * @param {Object} [param2.props]
     * @param {Object} [param2.options]
     * @param {number} [param2.options.width]
     * @param {number} [param2.options.height]
     * @param {number} [param2.options.aspectRatio=16/9]
     * @param {boolean} [param2.options.useAlternativeAssets]
     * @returns {Promise<Window|null>}
     */
    async pip(
        id,
        component,
        {
            props,
            options: {
                width,
                height,
                aspectRatio = 16 / 9,
                useAlternativeAssets = false,
            } = {},
        } = {},
    ) {
        let externalWindow = this.popouts.get(id).externalWindow;
        if (!externalWindow || externalWindow.closed) {
            externalWindow = await this._openPipWindow(id, width, height, aspectRatio);
        }
        await this.reset(id, { useAlternativeAssets });
        this._mount(
            id,
            component,
            props,
            Object.assign({}, this.env, { pipWindow: externalWindow }),
        );
        return externalWindow;
    }

    /**
     * @param {any} id
     * @param {typeof import("@odoo/owl").Component} component
     * @param {Object} props
     * @returns {Window}
     */
    popout(id, component, props) {
        const popout = this.popouts.get(id);
        if (!popout.externalWindow || popout.externalWindow.closed) {
            popout.hooks?.beforePopout?.();
            this._track(id, browser.open("about:blank", "_blank", "popup=yes"));
        }
        this.reset(id);
        this._mount(id, component, props);
        return popout.externalWindow;
    }

    /**
     * @param {any} id
     * @returns {Window|null}
     */
    getExternalWindow(id) {
        const externalWindow = this.popouts.get(id)?.externalWindow;
        return externalWindow && !externalWindow.closed ? externalWindow : null;
    }

    /**
     * @param {any} id
     * @param {{beforePopout?: () => void, afterPopoutClosed?: () => void}} hooks
     */
    addHooks(id, hooks) {
        this.popouts.get(id).hooks = hooks;
    }

    /** @param {any} id */
    createManager(id = DEFAULT_ID) {
        this.popouts.set(id, { externalWindow: null, generation: 0, hooks: {} });
        const service = this;
        return {
            /**
             * @param {Function} beforePopout
             * @param {Function} afterPopoutClosed
             */
            addHooks(beforePopout = () => {}, afterPopoutClosed = () => {}) {
                service.addHooks(id, { beforePopout, afterPopoutClosed });
            },

            /**
             * @param {Object} [props]
             * @returns {Promise<Window|null>}
             */
            async pip(component, props) {
                return service.pip(id, component, props);
            },

            /**
             * @param {Object} props
             * @returns {Window}
             */
            popout(component, props) {
                return service.popout(id, component, props);
            },

            reset() {
                service.reset(id);
            },

            /**
             * @returns {Window|null}
             */
            get externalWindow() {
                return service.getExternalWindow(id);
            },

            /** @returns {any} */
            get id() {
                return id;
            },
        };
    }
}

export const mailPopoutService = {
    /** @param {Window} window */
    async addAssets(window) {},

    /**
     * @param {import("@web/env").OdooEnv} env
     */
    start(env) {
        const service = new MailPopout(env);
        return Object.assign(service.createManager(), {
            createManager: (id) => service.createManager(id),
        });
    },
};

registry.category("services").add("mail.popout", mailPopoutService);
