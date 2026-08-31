// @ts-check
/** @odoo-module native */

import { EventBus, reactive } from "@odoo/owl";
import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { publishEnclosingScopeResolver } from "@web/core/utils/active_element_scope";
import { makeActiveElementStack } from "@web/ui/active_element_stack";
import { BlockUI } from "@web/ui/block/block_ui";
import { mainComponentEntry } from "@web/ui/main_components_container";
import { getMediaQueryLists, SIZES, utils } from "@web/ui/viewport";

// The focus half of this module lives next to the stack it drives. Re-exported
// here because `@web/ui/ui_service` is on the client's public surface.
export {
    getFirstAndLastTabableElements,
    useActiveElement,
} from "@web/ui/active_element";

class UiService {
    /** @param {import("@web/env").OdooEnv} env */
    constructor(env) {
        this.env = env;
        this.bus = new EventBus();
        /**
         * Replaced in setup(), which runs on the reactive proxy: a handler
         * built here would close over the raw instance and its writes would
         * notify nobody. Initialised only so the property is never undefined.
         *
         * @type {() => void}
         */
        this._onMediaChange = () => {};
        /**
         * @type {MediaQueryList[]}
         */
        this.subscribedMedias = [];
        this.blockCount = 0;
        this.activeElements = makeActiveElementStack();
        /**
         * @type {(() => void) | null}
         */
        this.withdrawScopeResolver = null;

        const initialSize = this.getSize();
        this.size = initialSize;
        /** @type {Document | HTMLElement} */
        this.activeElement = document;
        this.isBlocked = false;
        this.isSmall = initialSize <= SIZES.SM;
    }

    setup() {
        registry
            .category("main_components")
            .add("BlockUI", mainComponentEntry(BlockUI));

        this._onMediaChange = () => this.updateSize();
        this.subscribedMedias = getMediaQueryLists();
        for (const media of this.subscribedMedias) {
            media.addEventListener?.("change", this._onMediaChange);
        }

        Object.defineProperty(this.env, "isSmall", {
            configurable: true,
            get: () => this.isSmall,
        });
    }

    /**
     * @returns {number}
     */
    getSize() {
        return utils.getSize();
    }

    updateSize() {
        const size = this.getSize();
        if (size === this.size) {
            return;
        }
        this.size = size;
        this.isSmall = size <= SIZES.SM;
        this.bus.trigger(AppEvent.RESIZE);
    }

    /** @param {{ message?: string, delay?: number }} [data] */
    block(data) {
        this.blockCount++;
        this.isBlocked = true;
        if (this.blockCount === 1) {
            this.bus.trigger(AppEvent.BLOCK, {
                message: data?.message,
                delay: data?.delay,
            });
        }
    }

    unblock() {
        this.blockCount--;
        if (this.blockCount < 0) {
            console.warn(
                "Unblock ui was called more times than block, you should only unblock the UI if you have previously blocked it.",
            );
            this.blockCount = 0;
            return;
        }
        if (this.blockCount === 0) {
            this.isBlocked = false;
            this.bus.trigger(AppEvent.UNBLOCK);
        }
    }

    publishActiveElement() {
        this.activeElement = this.activeElements.current;
        this.bus.trigger(AppEvent.ACTIVE_ELEMENT_CHANGED, this.activeElement);
    }

    /** @param {HTMLElement} el */
    activateElement(el) {
        this.activeElements.activate(el);
        this.publishActiveElement();
    }

    /** @param {HTMLElement} el */
    deactivateElement(el) {
        if (this.activeElements.deactivate(el)) {
            this.publishActiveElement();
        }
    }

    /** @param {Node} el */
    getActiveElementOf(el) {
        return this.activeElements.activeElementOf(el);
    }

    /**
     * @param {Node | null} node
     * @returns {Document | HTMLElement}
     */
    getScopeOf(node) {
        return this.activeElements.scopeOf(node);
    }

    destroy() {
        this.withdrawScopeResolver?.();
        this.withdrawScopeResolver = null;
        for (const media of this.subscribedMedias) {
            media.removeEventListener?.("change", this._onMediaChange);
        }
        this.subscribedMedias = [];
        this.activeElements.reset();
        this.activeElement = this.activeElements.current;
        this.blockCount = 0;
        this.isBlocked = false;
        delete (/** @type {any} */ (this.env).isSmall);
    }
}

export const uiService = {
    /**
     * @param {import("@web/env").OdooEnv} env
     * @returns {UiService}
     */
    start(env) {
        const service = reactive(new UiService(env));
        service.setup();
        service.withdrawScopeResolver = publishEnclosingScopeResolver((node) =>
            service.getScopeOf(node),
        );
        return service;
    },
};

registry.category("services").add("ui", uiService);
