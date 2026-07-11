// @ts-check
/** @odoo-module native */

/** @module @web/legacy/js/public/public_root - Legacy PublicRoot widget that bootstraps the OWL app and public widget registry */

import { cookie } from "@web/core/browser/cookie";
import publicWidget from "@web/legacy/js/public/public_widget";

import lazyloader from "@web/legacy/js/public/lazyloader";

import { makeEnv, startServices } from "@web/env";
import { getTemplate } from "@web/core/templates";
import { MainComponentsContainer } from "@web/components/main_components_container";
import { browser } from "@web/core/browser/browser";
import { appTranslateFn } from "@web/core/l10n/translation";
import { jsToPyLocale, pyToJsLocale } from "@web/core/l10n/utils";
import { App, Component, whenReady } from "@odoo/owl";
import { RPCError } from "@web/core/network/rpc";
import { patch } from "@web/core/utils/patch";
import { Settings } from "@web/core/l10n/luxon";

// Load localizations outside the PublicRoot to not wait for DOM ready (but
// wait for them in PublicRoot)
function getLang() {
    const html = document.documentElement;
    return jsToPyLocale(html.getAttribute("lang")) || "en_US";
}
const lang = cookie.get("frontend_lang") || getLang(); // FIXME the cookie value should maybe be in the ctx?

// One-shot guard: the patch below targets the service prototype, so it must
// apply only once. The body reads this module-level ref (not a closure) so
// each PublicRoot.init reassigns it and a later root — not a stale one —
// gets its widgets started/stopped.
let interactionsServicePatched = false;
/** @type {any} */
let currentPublicRoot = null;

/**
 * Top-most widget in the hierarchy; all other widgets link to it indirectly.
 * Retrieves RPC demands from its children and handles them.
 */
// Cast to any: Widget is a legacy OdooClass whose .extend() is dynamic
export const PublicRoot = /** @type {any} */ (publicWidget.Widget).extend({
    events: {
        "submit .js_website_submit_form": "_onWebsiteFormSubmit",
        "click .js_disable_on_click": "_onDisableOnClick",
    },
    custom_events: {
        call_service: "_onCallService",
        context_get: "_onContextGet",
        main_object_request: "_onMainObjectRequest",
        widgets_start_request: "_onWidgetsStartRequest",
        widgets_stop_request: "_onWidgetsStopRequest",
    },

    /**
     * @constructor
     * @this {any}
     */
    init: function (_, env) {
        this._super.apply(this, arguments);
        this.env = env;
        this.publicWidgets = [];
        // Patch interaction_service so that it also starts and stops public
        // widgets.
        const interactionsService = this.env.services["public.interactions"];
        currentPublicRoot = this;
        if (interactionsService && !interactionsServicePatched) {
            interactionsServicePatched = true;
            // The `fromPublicRoot` option marks (re)starts/stops that the
            // PublicRoot widget machinery itself performs: for those the patch
            // must not start/stop widgets again. An explicit option (instead
            // of instance booleans set across awaits) keeps two overlapping
            // operations from reading each other's flag.
            patch(interactionsService.constructor.prototype, {
                /** @this {any} */
                startInteractions(el, options) {
                    super.startInteractions(el);
                    const publicRoot = currentPublicRoot;
                    if (publicRoot && !options?.fromPublicRoot) {
                        // this.editMode is assigned by website_edit_service
                        publicRoot._startWidgets(el || this.el, {
                            fromInteractionPatch: true,
                            editableMode: this.editMode,
                        });
                    }
                },
                /** @this {any} */
                stopInteractions(el, options) {
                    super.stopInteractions(el);
                    const publicRoot = currentPublicRoot;
                    if (publicRoot && !options?.fromPublicRoot) {
                        publicRoot._stopWidgets(el || this.el);
                    }
                },
            });
        }
    },
    /**
     * @override
     */
    start: function () {
        const defs = [
            this._super.apply(this, arguments),
            this._startWidgets(undefined, { starting: true }),
        ];

        // Display image thumbnail
        for (const el of this.el.querySelectorAll(
            ".o_image[data-mimetype^='image']",
        )) {
            if (
                /gif|jpe|jpg|png|webp/.test(el.dataset.mimetype) &&
                el.dataset.src
            ) {
                el.style.backgroundImage = `url('${el.dataset.src}')`;
            }
        }

        // Auto scroll
        const scrollTopMatch = window.location.hash.match(/scrollTop=([0-9]+)/);
        if (scrollTopMatch) {
            this.el.scrollTop = +scrollTopMatch[1];
        }

        return Promise.all(defs);
    },

    //--------------------------------------------------------------------------
    // Private
    //--------------------------------------------------------------------------

    /**
     * Retrieves the global context of the public environment. This is the
     * context which is automatically added to each RPC.
     *
     * @private
     * @param {Object} [context]
     * @returns {Object}
     */
    _getContext: function (context) {
        return Object.assign(
            {
                lang: getLang(),
            },
            context || {},
        );
    },
    /**
     * Retrieves the global context of the public environment (as
     * @see _getContext) but with extra informations that would be useless to
     * send with each RPC.
     *
     * @private
     * @param {Object} [context]
     * @returns {Object}
     */
    _getExtraContext: function (context) {
        return this._getContext(context);
    },
    /**
     * @private
     * @param {Object} [options]
     * @returns {Object}
     */
    _getPublicWidgetsRegistry: function (options) {
        return publicWidget.registry;
    },
    /**
     * Restarts interactions from the specified targetEl, or from #wrapwrap.
     *
     * @private
     * @param {HTMLElement} targetEl
     * @param {Object} [options]
     */
    _restartInteractions(targetEl, options) {
        const publicInteractions = this.bindService("public.interactions");
        // fromPublicRoot: _startWidgets already handles the widgets around
        // this restart; the interaction-service patch must not re-enter.
        publicInteractions.stopInteractions(targetEl, { fromPublicRoot: true });
        publicInteractions.startInteractions(targetEl, { fromPublicRoot: true });
    },
    /**
     * Creates a PublicWidget instance for each DOM element which matches the
     * `selector` key of one of the registered widgets
     * (@see PublicWidget.selector).
     *
     * @private
     * @param {HTMLElement|HTMLElement[]} [from]
     *        only initialize the public widgets whose `selector` matches the
     *        element or one of its descendant (default to the wrapwrap element)
     * @param {Object} [options]
     * @returns {Promise}
     */
    _startWidgets: function (from, options) {
        const self = this;

        if (from === undefined) {
            from = this.el.querySelector("#wrapwrap");
            if (!from) {
                // TODO Remove this once all frontend layouts possess a
                // #wrapwrap element (which is necessary for those pages to be
                // adapted correctly if the user installs website).
                from = this.el;
            }
        }
        // Normalize to array
        const fromEls =
            from instanceof NodeList || Array.isArray(from)
                ? [...from]
                : [from];

        this._stopWidgets(fromEls);
        if (!options?.starting && !options?.fromInteractionPatch) {
            for (const fromEl of fromEls) {
                this._restartInteractions(fromEl, options);
            }
        }

        const defs = Object.values(this._getPublicWidgetsRegistry(options)).map(
            (PublicWidget) => {
                const selector = PublicWidget.prototype.selector;
                if (!selector) {
                    return;
                }
                const selectorHas = PublicWidget.prototype.selectorHas;
                const selectorFunc =
                    typeof selector === "function"
                        ? selector
                        : (fromEl) => {
                              const els = [
                                  ...fromEl.querySelectorAll(selector),
                              ];
                              if (fromEl.matches(selector)) {
                                  els.push(fromEl);
                              }
                              return els;
                          };

                let targetEls = [];
                for (const fromEl of fromEls) {
                    targetEls.push(...selectorFunc(fromEl));
                }
                if (selectorHas) {
                    targetEls = targetEls.filter(
                        (el) => !!el.querySelector(selectorHas),
                    );
                }

                const proms = targetEls.map((el) => {
                    const widget = new PublicWidget(self, options);
                    self.publicWidgets.push(widget);
                    return widget.attachTo(el);
                });
                return Promise.all(proms);
            },
        );
        return Promise.all(defs);
    },
    /**
     * Destroys all registered widget instances. Website would need this before
     * saving while in edition mode for example.
     *
     * @private
     * @param {HTMLElement|HTMLElement[]} [from]
     *        only stop the public widgets linked to the given element(s) or one
     *        of its descendants
     */
    _stopWidgets: function (from) {
        // Normalize to array
        const fromEls =
            from instanceof NodeList || Array.isArray(from)
                ? [...from]
                : from
                  ? [from]
                  : null;

        const removedWidgets = this.publicWidgets.map((widget) => {
            if (
                !fromEls ||
                fromEls.some((el) => el === widget.el) ||
                fromEls.some((el) => el.contains(widget.el))
            ) {
                widget.destroy();
                return widget;
            }
            return null;
        });
        this.publicWidgets = this.publicWidgets.filter(
            (x) => removedWidgets.indexOf(x) < 0,
        );
    },

    //--------------------------------------------------------------------------
    // Handlers
    //--------------------------------------------------------------------------

    /**
     * Calls the requested service from the env. Automatically adds the global
     * context to RPCs.
     *
     * @private
     * @param {any} ev
     */
    _onCallService: function (ev) {
        const payload = ev.data;
        const service = this.env.services[payload.service];
        const result = service[payload.method].apply(
            service,
            payload.args || [],
        );
        payload.callback(result);
        ev.stopPropagation();
    },
    /**
     * Called when someone asked for the global public context.
     *
     * @private
     * @param {any} ev
     */
    _onContextGet: function (ev) {
        if (ev.data.extra) {
            ev.data.callback(this._getExtraContext(ev.data.context));
        } else {
            ev.data.callback(this._getContext(ev.data.context));
        }
    },
    /**
     * Checks information about the page main object.
     *
     * @private
     * @param {any} ev
     */
    _onMainObjectRequest: function (ev) {
        const repr = document.documentElement.dataset.mainObject;
        const m = repr.match(/(.+)\((-?\d+),(.*)\)/);
        ev.data.callback({
            model: m[1],
            id: Number(m[2]),
        });
    },
    /**
     * Called when the root is notified that the public widgets have to be
     * (re)started.
     *
     * @private
     * @param {any} ev
     */
    async _onWidgetsStartRequest(ev) {
        try {
            const target = ev.data.$target;
            await this._startWidgets(target, ev.data.options);
            ev.data.onSuccess?.();
        } catch (e) {
            ev.data.onFailure?.(e);
            if (!(e instanceof RPCError)) {
                throw e;
            }
        }
    },
    /**
     * Called when the root is notified that the public widgets have to be
     * stopped.
     *
     * @private
     * @param {any} ev
     */
    _onWidgetsStopRequest: function (ev) {
        const target = ev.data.$target;
        this._stopWidgets(target);
        // also stops interactions; fromPublicRoot: the widgets were just
        // stopped above, the interaction-service patch must not redo it.
        const targetEl = Array.isArray(target) ? target[0] : target;
        const publicInteractions = this.bindService("public.interactions");
        publicInteractions.stopInteractions(targetEl, { fromPublicRoot: true });
    },
    /**
     * @private
     */
    _onWebsiteFormSubmit: function (ev) {
        const buttons = ev.currentTarget.querySelectorAll(
            'button[type="submit"], a.a-submit',
        );
        for (const btn of buttons) {
            btn.insertAdjacentHTML(
                "afterbegin",
                '<i class="fa-solid fa-circle-notch fa-spin"></i> ',
            );
            btn.disabled = true;
        }
    },
    /**
     * Called when the root is notified that the button should be
     * disabled after the first click.
     *
     * @private
     * @param {Event} ev
     */
    _onDisableOnClick: function (ev) {
        /** @type {HTMLElement} */ (ev.currentTarget).classList.add("disabled");
    },
});

/**
 * Creates and starts a PublicRoot widget, mounting it on document.body. The
 * tour manager needs this root as a service provider so it can report
 * consumed tours back to the server.
 *
 * @param {typeof PublicRoot} RootWidget
 * @returns {Promise<InstanceType<typeof PublicRoot>>}
 */
export async function createPublicRoot(RootWidget) {
    await lazyloader.allScriptsLoaded;
    await whenReady();
    const env = makeEnv();
    await startServices(env);

    env.services["public.interactions"].isReady.then(() => {
        document.body.setAttribute("is-ready", "true");
    });

    // @ts-expect-error -- OWL Component.env is assigned at startup (legacy pattern)
    Component.env = env;
    const publicRoot = new RootWidget(null, env);
    const app = new App(/** @type {any} */ (MainComponentsContainer), {
        getTemplate,
        env,
        dev: /** @type {any} */ (env.debug),
        translateFn: appTranslateFn,
        translatableAttributes: ["data-tooltip"],
    });
    const locale = pyToJsLocale(lang) || browser.navigator.language;
    Settings.defaultLocale = locale;
    const [root] = await Promise.all([
        app.mount(document.body),
        publicRoot.attachTo(document.body),
    ]);
    // @ts-expect-error -- debug property assigned to odoo global at runtime
    odoo.__WOWL_DEBUG__ = { root };
    return publicRoot;
}

export default { PublicRoot, createPublicRoot };
