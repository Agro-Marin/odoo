/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { omit } from "@web/core/utils/collections/objects";
import { patch } from "@web/core/utils/patch";
import * as bootstrap from "@web/libs/bootstrap";
import { Colibri } from "@web/public/colibri";
import { Interaction } from "@web/public/interaction";

const EDIT_HOOKS_KEY = "__odooWebsiteEditHooks";

const EDIT_BOOTSTRAP_KEY = "__odooWebsiteEditBootstrap";
window[EDIT_BOOTSTRAP_KEY] = bootstrap;

export function buildEditableInteractions(builders) {
    const result = [];

    const mixinPerInteraction = new Map();
    for (const makeEditable of builders) {
        mixinPerInteraction.set(
            makeEditable.Interaction,
            makeEditable.mixin || ((C) => C),
        );
    }
    for (const makeEditable of builders) {
        if (makeEditable.isAbstract) {
            continue;
        }
        let I = makeEditable.Interaction;
        const mixins = [];
        while (I && I !== Interaction) {
            const mixin = mixinPerInteraction.get(I);
            if (mixin) {
                mixins.push(mixin);
            } else {
                console.warn(`No mixin defined for: ${I.name}`);
            }
            I = I.__proto__;
        }
        let EI = makeEditable.Interaction;
        while (mixins.length) {
            EI = mixins.pop()(EI);
        }
        if (!EI.name) {
            const name = makeEditable.Interaction.name + "__mixin";
            EI = { [name]: class extends EI {} }[name];
        }
        result.push(EI);
    }
    return result;
}

const log = makeLogger("website.edit");

export const websiteEditService = {
    dependencies: ["public.interactions"],
    start(env, { ["public.interactions"]: publicInteractions }) {
        let editableInteractions = null;
        let previewInteractions = null;
        const patches = [];
        const historyCallbacks = {};
        const shared = {};

        const update = (target, mode) => {
            log.pipeline("update", () => ({
                mode,
                target: target?.tagName,
                refreshing: publicInteractions.isRefreshing,
            }));
            stopDisconnectedInteractions();
            publicInteractions.stopInteractions(target);
            if (mode === "edit") {
                if (!editableInteractions) {
                    const builders = registry
                        .category("public.interactions.edit")
                        .getAll();
                    editableInteractions = buildEditableInteractions(builders);
                }
                publicInteractions.editMode = true;
                publicInteractions.activate(editableInteractions);
            } else if (mode === "preview") {
                if (!previewInteractions) {
                    const builders = registry
                        .category("public.interactions.preview")
                        .getAll();
                    previewInteractions = buildEditableInteractions(builders);
                }
                publicInteractions.activate(previewInteractions, target);
            } else {
                publicInteractions.startInteractions(target);
            }
        };

        const refresh = (target) => {
            publicInteractions.isRefreshing = true;
            try {
                update(target, "edit");
            } finally {
                publicInteractions.isRefreshing = false;
            }
        };

        const stop = (target) => {
            log.lifecycle("stop", () => ({ target: target?.tagName }));
            publicInteractions.stopInteractions(target);
        };

        const stopInteraction = (name) => {
            publicInteractions.stopInteractionsByName(name);
        };

        const stopDisconnectedInteractions = () => {
            publicInteractions.stopDisconnectedInteractions();
        };

        const isEditingTranslations = () =>
            !!publicInteractions.el.closest("html").dataset.edit_translations;

        const installPatches = () => {
            if (patches.length) {
                return;
            }

            publicInteractions.domEffectScope = (fn) =>
                historyCallbacks.ignoreDOMMutations(fn);
            patches.push(() => {
                delete publicInteractions.domEffectScope;
            });

            patches.push(
                patch(Colibri.prototype, {
                    setupInteraction() {
                        super.setupInteraction();
                        this.interaction.setupConfigurationSnapshot();
                    },
                    addListener(target, event, fn, options, sel) {
                        if (event.startsWith("slide.bs.carousel")) {
                            const inner = fn;
                            fn = /** @type {any} */ (
                                function (/** @type {any[]} */ ...args) {
                                    const ev = args[0];
                                    ev.preventDefault = () => {};
                                    ev.stopPropagation = () => {};
                                    return inner.call(this, ...args);
                                }
                            );
                        }
                        return super.addListener(target, event, fn, options, sel);
                    },
                }),
                patch(Interaction.prototype, {
                    setupConfigurationSnapshot() {
                        this.configurationSnapshot = this.getConfigurationSnapshot();
                    },
                    getConfigurationSnapshot() {
                        const dataset = omit(this.el.dataset, "visibility");
                        const style = {};
                        for (const property of this.el.style) {
                            if (property.startsWith("animation")) {
                                if (property === "animation-play-state") {
                                    continue;
                                }
                                style[property] = this.el.style[property];
                            }
                        }
                        if (Object.keys(dataset).length || Object.keys(style).length) {
                            return JSON.stringify({ dataset, style });
                        }
                        return NaN;
                    },
                    shouldStop() {
                        if (!this.el.isConnected) {
                            return true;
                        }
                        const I = this.constructor;
                        let isMatch = this.el.matches(I.selector);
                        if (I.selectorHas) {
                            isMatch &&= !!this.el.querySelector(I.selectorHas);
                        }
                        if (I.selectorNotHas) {
                            isMatch &&= !this.el.querySelector(I.selectorNotHas);
                        }
                        if (!isMatch) {
                            return true;
                        }
                        const snapshot = this.getConfigurationSnapshot();
                        if (snapshot === this.configurationSnapshot) {
                            return false;
                        }
                        this.configurationSnapshot = snapshot;
                        return true;
                    },
                    isImpactedBy(el) {
                        return false;
                    },
                    insert(...args) {
                        const el = args[0];
                        super.insert(...args);
                        el.setAttribute("contenteditable", "false");
                    },
                }),
                patch(publicInteractions.constructor.prototype, {
                    shouldStop(el, interaction) {
                        if (this.isRefreshing) {
                            const mustBeRefreshed =
                                super.shouldStop(el, interaction) ||
                                interaction.interaction.isImpactedBy(el);
                            return (
                                mustBeRefreshed && interaction.interaction.shouldStop()
                            );
                        }
                        return super.shouldStop(el, interaction);
                    },
                }),
            );
        };
        const uninstallPatches = () => {
            for (const removePatch of patches) {
                removePatch();
            }
            patches.length = 0;
            delete window[EDIT_HOOKS_KEY];
        };
        const applyAction = (actionId, spec) => {
            log.logic("applyAction", () => ({ actionId, spec }));
            shared.builderActions.applyAction(actionId, spec);
        };
        const callShared = (pluginName, methodName, args = []) => {
            if (!Array.isArray(args)) {
                args = [args];
            }
            log.logic("callShared", () => ({
                pluginName,
                methodName,
                known: Boolean(shared[pluginName]?.[methodName]),
            }));
            if (shared[pluginName]) {
                if (shared[pluginName][methodName]) {
                    return shared[pluginName][methodName](...args);
                } else {
                    console.error(
                        `Method "${methodName}" not found on plugin "${pluginName}".`,
                    );
                }
            } else {
                console.error(`Plugin "${pluginName}" not found.`);
            }
        };

        const websiteEditService = {
            isEditingTranslations,
            update,
            refresh,
            stop,
            stopInteraction,
            installPatches,
            uninstallPatches,
            applyAction,
            callShared,
        };

        const handleEditPage = (ev) => {
            stop(ev.detail.iframeDocument);
        };

        const handlePluginLoaded = (ev) => {
            ev.currentTarget.dispatchEvent(
                new CustomEvent("transfer_website_edit_service", {
                    detail: {
                        websiteEditService,
                    },
                }),
            );
            Object.assign(shared, ev.shared);
            historyCallbacks.ignoreDOMMutations = shared.history.ignoreDOMMutations;
            window[EDIT_HOOKS_KEY] = {
                ...window[EDIT_HOOKS_KEY],
                ignoreDOMMutations: shared.history.ignoreDOMMutations,
            };
        };

        window.parent.document.addEventListener("edit_page", handleEditPage);
        window.parent.document.addEventListener(
            "edit_interaction_plugin_loaded",
            handlePluginLoaded,
        );
        window.parent.document.dispatchEvent(
            new CustomEvent("website_edit_service_ready"),
        );

        window.addEventListener("beforeunload", () => {
            window.parent.document.removeEventListener("edit_page", handleEditPage);
            window.parent.document.removeEventListener(
                "edit_interaction_plugin_loaded",
                handlePluginLoaded,
            );
        });

        return websiteEditService;
    },
};
registry.category("services").add("website_edit", websiteEditService);

/**
 * @param {string | number} snapshot
 * @returns {boolean}
 */
export function isTrackedSnapshot(snapshot) {
    return typeof snapshot === "string";
}

export function withHistory(dynamicContent) {
    const result = {};
    for (const [selector, content] of Object.entries(dynamicContent)) {
        result[selector] = {};
        for (const [key, value] of Object.entries(content)) {
            result[selector][key.startsWith("t-on-") ? `${key}.keepInHistory` : key] =
                value;
        }
    }
    return result;
}
