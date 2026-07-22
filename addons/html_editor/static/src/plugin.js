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
        /** @type { EditorContext['document'] } **/
        this.document = context.document;
        this.window = context.document.defaultView;
        /** @type { EditorContext['editable'] } **/
        this.editable = context.editable;
        /** @type { EditorContext['config'] } **/
        this.config = context.config;
        /** @type { EditorContext['services'] } **/
        this.services = context.services;
        /** @type { EditorContext['dependencies'] } **/
        this.dependencies = context.dependencies;
        /** @type { EditorContext['getResource'] } **/
        this.getResource = context.getResource;
        /** @type { EditorContext['dispatchTo'] } **/
        this.dispatchTo = context.dispatchTo;
        /** @type { EditorContext['delegateTo'] } **/
        this.delegateTo = context.delegateTo;
        /** @type { EditorContext['checkPredicates'] } **/
        this.checkPredicates = context.checkPredicates;

        this._cleanups = [];
        this.isDestroyed = false;
    }

    setup() {}

    isValidTargetForDomListener(ev) {
        return isValidTargetForDomListener(ev.target);
    }

    /**
     * Add an event listener on a given target, that will only be executed if
     * the target is valid (unless `isGlobal` is true), and ensure it is removed
     * when we destroy the editor.
     *
     * @param {Element} target
     * @param {string} eventName
     * @param {function(Event):void} fn
     * @param {boolean | AddEventListenerOptions} [capture=false] `useCapture`
     *   flag of `addEventListener`, or a full options object. Several call
     *   sites pass `{ capture: true }`; that already worked because
     *   `addEventListener` accepts either form, but the annotation claimed
     *   boolean only. The same value is handed to `removeEventListener`, which
     *   is what makes the cleanup match.
     * @param {boolean} [isGlobal=false] if true, don't check target validity
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
     * Add an event listener on the editor's document, and ensure it is removed
     * when we destroy the editor.
     *
     * @todo Use this function to avoid iframe problems.
     *
     * @param {string} eventName
     * @param {function(Event):void} fn
     * @param {boolean} [capture=false] `useCapture` flag of `addEventListener`
     */
    addGlobalDomListener(eventName, fn, capture = false) {
        this.addDomListener(this.document, eventName, fn, capture, true);
    }

    /**
     * Register listeners that live only for the duration of an interaction
     * (typically a pointer drag) and return a disposer that removes them.
     *
     * Unlike {@link addDomListener}, the registration is undone once the
     * interaction ends, so repeated drags do not accumulate cleanups. Unlike a
     * raw `addEventListener`, the listeners are still removed if the editor is
     * destroyed while the interaction is in progress — otherwise they outlive
     * the editor and keep calling into a destroyed plugin.
     *
     * @param {EventTarget} target
     * @param {Record<string, function(Event):void>} handlers
     * @returns {() => void} disposer, idempotent
     */
    addTransientDomListeners(target, handlers) {
        const entries = Object.entries(handlers);
        for (const [eventName, fn] of entries) {
            target.addEventListener(eventName, fn);
        }
        const dispose = () => {
            const index = this._cleanups.indexOf(dispose);
            if (index === -1) {
                return; // already disposed
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
        // Iterate a snapshot: a cleanup may deregister itself (and therefore
        // splice `_cleanups`), which would make a live iteration skip entries.
        for (const cleanup of [...this._cleanups]) {
            cleanup();
        }
        this._cleanups = [];
        this.isDestroyed = true;
    }
}
