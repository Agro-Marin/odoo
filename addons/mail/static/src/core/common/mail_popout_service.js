/** @odoo-module native */
import { App } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { appTranslateFn } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { getTemplate } from "@web/core/templates";
const DEFAULT_ID = Symbol("default");

export const mailPopoutService = {
    /**
     * To be overridden to add specific assets to call PiP.
     * @param [Window] window the window on which we may add assets
     */
    async addAssets(window) {},

    start(env) {
        /**
         * @type {Map<any, { externalWindow: Window|null, generation: number, hooks: { beforePopout?: Function, afterPopoutClosed?: Function, app: App } }>}
         */
        const popouts = new Map();

        // Close any still-open popout windows when the main window unloads.
        // Registered ONCE for the service's lifetime — the previous code added
        // a fresh `beforeunload` listener inside popout() on every open, none
        // of which were ever removed (and pip() had no such cleanup at all).
        // `browser`, not the raw global: the service is instantiated per test,
        // and going straight to `window` kept every such instance subscribed
        // for the rest of the run (@see store_service.js `onStarted`). The test
        // harness tracks and detaches listeners added through this seam during
        // a test (@see web/static/tests/_framework/module_set.hoot.js). Held in
        // a named binding so it can be removed; services have no teardown hook
        // here, so in production its lifetime is the page's.
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
         * Reset the external window to its initial state:
         * - Reset the external window header from main window (for appropriate title and other meta data)
         * - clear the external window's document body
         * - destroy the current app mounted on the window
         * @param {any} id - The ID of the popout instance to reset
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
         * Poll the external window to detect when it is closed.
         * the afterPopoutClosed hook (afterFn) is then called after the window is closed
         *
         * @param {any} id
         * @param {number} generation - token of the window this poller owns
         */
        async function pollClosedWindow(id, generation) {
            // A poller only ever owns the window it was started for: reopening
            // within the 1s tick used to leave the previous poller looping
            // forever on the new window, and whichever poller lost the race
            // never fired `afterPopoutClosed` for the close it detected.
            while (
                popouts.get(id)?.externalWindow &&
                popouts.get(id).generation === generation
            ) {
                const popout = popouts.get(id);
                await new Promise((r) => setTimeout(r, 1000));
                if (popout.generation !== generation) {
                    return;
                }
                if (popout.externalWindow?.closed) {
                    const hooks = popout.hooks;
                    hooks?.afterPopoutClosed?.();
                    popout.externalWindow = null;
                    // Destroy the OWL app mounted on the now-dead document:
                    // `reset()` was the only teardown site and no consumer
                    // called it on close, so the component tree stayed mounted
                    // and subscribed to the store reactives (e.g. call PiP's
                    // `Meeting`). `reset()` tolerates a null externalWindow.
                    await reset(id);
                }
            }
        }

        /**
         * @param id
         * @param component
         * @param {Object} param2
         * @param {Object} [param2.props]
         * @param {Object} [param2.options]
         *      If only one of width or height is provided, the other is calculated based on the aspect ratio.
         *      If neither is provided, a default height of 320p is used.
         * @param {number} [param2.options.width] - The width of the popout window.
         * @param {number} [param2.options.height] - The height of the popout window.
         * @param {number} [param2.options.aspectRatio=16/9] - The aspect ratio of the popout window.
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
                // `window`, not `browser`: the facade does not expose
                // `documentPictureInPicture` (@see web/core/browser/browser.js),
                // so going through it would silently disable native PiP.
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
                // one poller per window creation, identified by its token
                popout.generation++;
                pollClosedWindow(id, popout.generation);
            }
            await reset(id, { useAlternativeAssets });
            popout.app = new App(component, {
                name: "Popout",
                env: Object.assign({}, env, {
                    /**
                     * Some sub components may need a reference to the external window to
                     * access window information such as its dimensions, or to attach event listeners.
                     */
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
         * Mounts the passed component (with its props) on an external window.
         * If the external window does not exist, it is created.
         */
        function popout(id, component, props) {
            const popout = popouts.get(id);
            let externalWindow = popout.externalWindow;
            if (!externalWindow || externalWindow.closed) {
                const hooks = popout.hooks;
                hooks?.beforePopout?.();
                externalWindow = browser.open("about:blank", "_blank", "popup=yes");
                popout.externalWindow = externalWindow;
                // one poller per window creation, identified by its token
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

        function getExternalWindow(id) {
            const externalWindow = popouts.get(id)?.externalWindow;
            return externalWindow && !externalWindow.closed ? externalWindow : null;
        }

        function addHooks(id, hooks) {
            const popout = popouts.get(id);
            popout.hooks = hooks;
        }

        /**
         * Creates an ID-aware popout manager for a specific ID.
         * This allows using multiple popout instances with different IDs,
         *
         * @param {any} id - An identifier for this popout instance
         */
        function createManager(id = DEFAULT_ID) {
            popouts.set(id, {
                externalWindow: null,
                generation: 0,
                hooks: {},
            });
            return {
                /**
                 * Registers hooks for this popout instance.
                 * @param {Function} beforePopout - called before the external window is created.
                 * @param {Function} afterPopoutClosed - called after the external window is closed.
                 */
                addHooks(beforePopout = () => {}, afterPopoutClosed = () => {}) {
                    addHooks(id, { beforePopout, afterPopoutClosed });
                },

                /**
                 * Creates a picture-in-picture window and mounts the component
                 * @param component - The component to be mounted.
                 * @param {Props} props - The props of the component.
                 * @returns {Promise<Window>} The external window
                 */
                async pip(component, props) {
                    return pip(id, component, props);
                },

                /**
                 * Creates a popup window and mounts the component
                 * @param component - The component to be mounted.
                 * @param {Props} props - The props of the component.
                 * @returns {Window} The external window
                 */
                popout(component, props) {
                    return popout(id, component, props);
                },

                /**
                 * Resets this popout instance to its initial state
                 */
                reset() {
                    reset(id);
                },

                /**
                 * Gets the external window for this ID
                 * @returns {Window|null} The external window or null if closed/doesn't exist
                 */
                get externalWindow() {
                    return getExternalWindow(id);
                },

                /**
                 * Gets the ID of this manager
                 * @returns {any} The ID
                 */
                get id() {
                    return id;
                },
            };
        }

        return Object.assign(createManager(), { createManager });
    },
};

registry.category("services").add("mail.popout", mailPopoutService);
