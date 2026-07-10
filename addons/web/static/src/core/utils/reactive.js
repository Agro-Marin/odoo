// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/reactive - SignalStore base class and side-effect helper for OWL reactivity system */

import { reactive } from "@odoo/owl";

/**
 * Base class for stateful entities that want OWL's reactivity system to
 * observe every mutation made through ``this``.  Subclasses auto-wrap
 * their own instance in ``reactive(this)`` at construction time, which
 * means any callback registered from the constructor that mutates
 * ``this.<field>`` will notify observers — the property access goes
 * through the Proxy returned by ``reactive()``, not through the raw
 * (pre-wrapping) receiver.
 *
 * Aligned with 2026 frontend vocabulary (Solid ``createSignal`` /
 * Svelte 5 ``$state`` / Vue 3 ``ref``): a class whose instances are
 * shared, observable state containers.  Historically named ``Reactive``;
 * the alias was dropped 2026-05-09 after a fork-wide grep confirmed
 * zero in-tree consumers (eslint had banned new imports for weeks).
 *
 * Why the base class exists at all: without it, callbacks captured in
 * the constructor reference the raw ``this`` (pre-proxy) and mutations
 * through them escape reactivity.  Example of the bug it solves:
 *
 *     const bus = new EventBus();
 *     class MyClass {
 *       constructor() {
 *         this.counter = 0;
 *         bus.addEventListener("change", () => this.counter++);
 *         //                                   ^ captures raw `this`
 *         //                                     — mutations missed
 *       }
 *     }
 *     const myObj = reactive(new MyClass(bus), () => console.log(myObj.counter));
 *     myObj.counter++;      // logs 1
 *     bus.trigger("change"); // logs nothing!  counter == 2 but callback silent
 *
 * By extending ``SignalStore`` and calling ``super()`` first, the
 * constructor's ``this`` *is* the proxy, so callbacks that close over
 * ``this`` participate in reactivity.
 */
export class SignalStore {
    constructor() {
        return reactive(this);
    }
}

/**
 * Creates a side-effect that runs based on the content of reactive objects.
 *
 * This is the **process-scoped** reactive effect, distinct from OWL's
 * **component-scoped** ``useEffect`` (which only fires while the owning
 * component is mounted). Use this when state mutations outside any
 * component need to trigger a callback — e.g. a service observing a
 * shared store, a record-level dependency tracker that outlives any
 * single render.
 *
 * Initial behavior: ``cb`` runs synchronously at registration time so
 * the callback sees the current state on the first tick. Subsequent
 * runs fire when any of the proxied dependencies mutate.
 *
 * @template {object[]} T
 * @param {(...args: [...T]) => any} cb callback for the effect
 * @param {[...T]} deps the reactive objects that the effect depends on
 */
export function effect(cb, deps) {
    const reactiveDeps = reactive(deps, () => {
        cb(...reactiveDeps);
    });
    cb(...reactiveDeps);
}

/**
 * Same as {@link effect}, but returns a function to dispose of the effect.
 *
 * Unlike a plain ``effect``, which keeps firing after its observer is gone,
 * this stops once disposed — call the returned function on teardown (e.g.
 * ``onWillDestroy``). Disposal works by making the callback read no reactive
 * key on its next run, which releases OWL's subscriptions for good.
 *
 * @template {object[]} T
 * @param {(...args: [...T]) => any} cb callback for the effect
 * @param {[...T]} deps the reactive objects that the effect depends on
 * @returns {() => void} a function to dispose of the effect
 */
export function disposableEffect(cb, deps) {
    let disposed = false;
    const reactiveDeps = reactive(deps, () => {
        if (disposed) {
            // Reading no reactive key here releases the subscriptions.
            return;
        }
        cb(...reactiveDeps);
    });
    cb(...reactiveDeps);
    return () => {
        disposed = true;
    };
}
