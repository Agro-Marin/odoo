/** @odoo-module native */
import { App } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { getTemplate } from "@web/core/templates";
import { appTranslateFn } from "@web/core/translation";
const DEFAULT_ID = Symbol("default");

export const mailPopoutService = {
    /** @param {Window} window */
    async addAssets(window) {},

    /**
     * @param {import("@web/env").OdooEnv} env
     */
    start(env) {
        /**
         * @type {Map<any, { externalWindow: Window|null, generation: number, hooks: { beforePopout?: Function, afterPopoutClosed?: Function }, app?: App }>}
         */
        const popouts = new Map();

        const onBeforeUnload = () => {
            for (const popout of popouts.values()) {
                const externalWindow = popout.externalWindow;
                if (externalWindow && !externalWindow.closed) {
                    externalWindow.close();
                }
            }
        };
        browser.addEventListener("beforeunload", onBeforeUnload);

        /**
         * @param {any} id
         * @param {Object} [options]
         * @param {Boolean} [options.useAlternativeAssets]
         */
        async function reset(id, { useAlternativeAssets } = {}) {
            const popout = popouts.get(id);
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
        async function pollClosedWindow(id, generation) {
            while (
                popouts.get(id)?.externalWindow &&
                popouts.get(id).generation === generation
            ) {
                const popout = popouts.get(id);
                await new Promise((r) => browser.setTimeout(r, 1000));
                if (popout.generation !== generation) {
                    return;
                }
                if (popout.externalWindow?.closed) {
                    const hooks = popout.hooks;
                    hooks?.afterPopoutClosed?.();
                    popout.externalWindow = null;
                    await reset(id);
                }
            }
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
        async function pip(
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
            const popout = popouts.get(id);
            let externalWindow = popout.externalWindow;
            if (!externalWindow || externalWindow.closed) {
                const hooks = popout.hooks;
                hooks?.beforePopout?.();
                height =
                    height ||
                    (width ? width / aspectRatio : Math.min(240, browser.innerHeight));
                width = width || height * aspectRatio;
                if (window.documentPictureInPicture) {
                    externalWindow =
                        await window.documentPictureInPicture.requestWindow({
                            width,
                            height,
                        });
                } else {
                    externalWindow = browser.open(
                        "about:blank",
                        "_blank",
                        `popup=yes,width=${width},height=${height}`,
                    );
                }
                popout.externalWindow = externalWindow;
                popout.generation++;
                pollClosedWindow(id, popout.generation);
            }
            await reset(id, { useAlternativeAssets });
            popout.app = new App(component, {
                name: "Popout",
                env: Object.assign({}, env, {
                    pipWindow: externalWindow,
                }),
                props,
                getTemplate,
                translatableAttributes: ["data-tooltip"],
                translateFn: appTranslateFn,
            });
            popout.app.mount(externalWindow.document.body);
            return externalWindow;
        }

        /**
         * @param {any} id
         * @param {typeof import("@odoo/owl").Component} component
         * @param {Object} props
         * @returns {Window}
         */
        function popout(id, component, props) {
            const popout = popouts.get(id);
            let externalWindow = popout.externalWindow;
            if (!externalWindow || externalWindow.closed) {
                const hooks = popout.hooks;
                hooks?.beforePopout?.();
                externalWindow = browser.open("about:blank", "_blank", "popup=yes");
                popout.externalWindow = externalWindow;
                popout.generation++;
                pollClosedWindow(id, popout.generation);
            }
            reset(id);
            popout.app = new App(component, {
                name: "Popout",
                env,
                props,
                getTemplate,
                translatableAttributes: ["data-tooltip"],
                translateFn: appTranslateFn,
            });
            popout.app.mount(externalWindow.document.body);
            return externalWindow;
        }

        /**
         * @param {any} id
         * @returns {Window|null}
         */
        function getExternalWindow(id) {
            const externalWindow = popouts.get(id)?.externalWindow;
            return externalWindow && !externalWindow.closed ? externalWindow : null;
        }

        /**
         * @param {any} id
         * @param {{beforePopout?: () => void, afterPopoutClosed?: () => void}} hooks
         */
        function addHooks(id, hooks) {
            const popout = popouts.get(id);
            popout.hooks = hooks;
        }

        /** @param {any} id */
        function createManager(id = DEFAULT_ID) {
            popouts.set(id, {
                externalWindow: null,
                generation: 0,
                hooks: {},
            });
            return {
                /**
                 * @param {Function} beforePopout
                 * @param {Function} afterPopoutClosed
                 */
                addHooks(beforePopout = () => {}, afterPopoutClosed = () => {}) {
                    addHooks(id, { beforePopout, afterPopoutClosed });
                },

                /**
                 * @param {Object} [props]
                 * @returns {Promise<Window|null>}
                 */
                async pip(component, props) {
                    return pip(id, component, props);
                },

                /**
                 * @param {Object} props
                 * @returns {Window}
                 */
                popout(component, props) {
                    return popout(id, component, props);
                },

                reset() {
                    reset(id);
                },

                /**
                 * @returns {Window|null}
                 */
                get externalWindow() {
                    return getExternalWindow(id);
                },

                /** @returns {any} */
                get id() {
                    return id;
                },
            };
        }

        return Object.assign(createManager(), { createManager });
    },
};

registry.category("services").add("mail.popout", mailPopoutService);
