/** @odoo-module native */
import { isProtected, isProtecting, isUnprotecting } from "./utils/dom_info.js";

export const isValidTargetForDomListener = (target) =>
    !isProtecting(target) && (!isProtected(target) || isUnprotecting(target));

/**
 * @typedef { import("./editor").Editor } Editor
 * @typedef { import("./editor").EditorContext } EditorContext
 */

export class Plugin {
    static id = "";
    static dependencies = [];
    static shared = [];
    static defaultConfig = {};

    /** @type {Partial<import("plugins").Resources>} */
    resources;

    /**
     * @param { EditorContext } context
     */
    constructor(context) {
        /** @type { EditorContext['document'] } */
        this.document = context.document;
        this.window = context.document.defaultView;
        /** @type { EditorContext['editable'] } */
        this.editable = context.editable;
        /** @type { EditorContext['config'] } */
        this.config = context.config;
        /** @type { EditorContext['services'] } */
        this.services = context.services;
        /** @type { EditorContext['dependencies'] } */
        this.dependencies = context.dependencies;
        /** @type { EditorContext['getResource'] } */
        this.getResource = context.getResource;
        /** @type { EditorContext['dispatchTo'] } */
        this.dispatchTo = context.dispatchTo;
        /** @type { EditorContext['delegateTo'] } */
        this.delegateTo = context.delegateTo;
        /** @type { EditorContext['checkPredicates'] } */
        this.checkPredicates = context.checkPredicates;

        this._cleanups = [];
        this.isDestroyed = false;
    }

    setup() {}

    isValidTargetForDomListener(ev) {
        return isValidTargetForDomListener(ev.target);
    }

    /**
     * @param {Element} target
     * @param {string} eventName
     * @param {function(Event):void} fn
     * @param {boolean | AddEventListenerOptions} [capture=false]
     * @param {boolean} [isGlobal=false]
     */
    addDomListener(target, eventName, fn, capture = false, isGlobal = false) {
        const handler = (ev) => {
            if (isGlobal || this.isValidTargetForDomListener(ev)) {
                fn?.call(this, ev);
            }
        };
        target.addEventListener(eventName, handler, capture);
        this._cleanups.push(() =>
            target.removeEventListener(eventName, handler, capture),
        );
    }

    /**
     * @param {string} eventName
     * @param {function(Event):void} fn
     * @param {boolean} [capture=false]
     */
    addGlobalDomListener(eventName, fn, capture = false) {
        this.addDomListener(this.document, eventName, fn, capture, true);
    }

    /**
     * @param {EventTarget} target
     * @param {Record<string, function(Event):void>} handlers
     * @returns {() => void}
     */
    addTransientDomListeners(target, handlers) {
        const entries = Object.entries(handlers);
        for (const [eventName, fn] of entries) {
            target.addEventListener(eventName, fn);
        }
        const dispose = () => {
            const index = this._cleanups.indexOf(dispose);
            if (index === -1) {
                return;
            }
            this._cleanups.splice(index, 1);
            for (const [eventName, fn] of entries) {
                target.removeEventListener(eventName, fn);
            }
        };
        this._cleanups.push(dispose);
        return dispose;
    }

    destroy() {
        for (const cleanup of [...this._cleanups]) {
            cleanup();
        }
        this._cleanups = [];
        this.isDestroyed = true;
    }
}
