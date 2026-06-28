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
 * Pairs with {@link derived} for read-side computation: ``effect`` is
 * the side-effect entry point; ``derived`` is the value-read entry
 * point. Together they cover the 2026 reactivity vocabulary
 * (Solid ``createEffect`` / ``createMemo``, Vue 3 ``watchEffect`` /
 * ``computed``, Svelte 5 ``$effect`` / ``$derived``).
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
 * Derived value backed by OWL's Proxy-based reactivity tracking.
 *
 * Wraps a thunk so consumers read it through ``.value``, matching the
 * 2026 frontend convention (Solid ``memo.value``, Vue 3 ``ref.value``,
 * Svelte 5 ``$derived`` accessors). The wrapper itself does nothing
 * clever: OWL's reactive Proxy tracks the property reads inside ``fn``
 * for whichever callback the read reactives are bound to — i.e. a
 * component render re-runs when ``fn`` reads that component's own
 * reactive state/props. It does NOT auto-subscribe an arbitrary
 * standalone ``reactive(derivedThing, cb)`` observer to ``fn``'s reads:
 * OWL binds callbacks at proxy-creation time with no execution-context
 * hook (see {@link memoizedDerived}). ``derived`` exists purely to give
 * *derived state* a grep-able name in the codebase.
 *
 * ```js
 * const total = derived(() =>
 *     cart.items.reduce((s, x) => s + x.price * cart.discount[x.id], 0)
 * );
 * // In a component template or another reactive consumer:
 * total.value
 * ```
 *
 * **When to reach for ``derived`` vs a class getter**:
 *
 * - **Class getter** when the derivation is naturally a property of an
 *   instance (``record.dirty``, ``coordinator.isSaving``,
 *   ``cart.total``). Consumers do ``record.dirty`` — terser, no
 *   ``.value`` step.
 * - **``derived``** when the derivation spans multiple sources,
 *   doesn't naturally belong to a class, or needs to be passed around
 *   as a value rather than accessed through an instance.
 *
 * **Why no memoization** (unlike Solid's ``createMemo`` or Vue's
 * ``computed``): the audit that motivated this primitive deliberately
 * left memoization out. OWL's reactive scheduler already batches
 * renders within a tick, so a getter accessed N times in one render is
 * called N times — but the cost is rarely measurable for typical UI
 * derivations, and a memoization layer would introduce cache-
 * invalidation bookkeeping that competes with OWL's own dependency
 * tracking. If a real perf bottleneck emerges around an expensive
 * derivation, introduce a memoized variant alongside (e.g.
 * ``memoized()``) rather than overloading this one.
 *
 * **Why a ``.value`` getter and not just a thunk** (``() => fn()``):
 * the property-access shape lets consumers pass ``derivedThing``
 * around as a stateful value object — the same way Vue's ``ref`` is
 * commonly passed into components as a prop. Templates and JSX can
 * also read ``foo.value`` ergonomically; a callable wrapper would
 * read ``foo()`` and conflict with method-binding conventions.
 *
 * @template T
 * @param {() => T} fn lazy thunk producing the derived value
 * @returns {{ readonly value: T }}
 */
export function derived(fn) {
    return {
        get value() {
            return fn();
        },
    };
}

/**
 * Memoized derived value backed by OWL's Proxy-based reactivity.
 *
 * Same shape as {@link derived} (read via ``.value``) but ``fn`` runs only
 * when one of the tracked ``deps`` has mutated since the last evaluation.
 * Repeated reads of ``.value`` between mutations share the cached result.
 *
 * Same call shape as {@link effect}: caller passes the reactive objects
 * fn depends on via ``deps``, and the primitive wraps them with an
 * invalidator callback before forwarding them to fn. This works around
 * OWL's per-proxy-creation callback binding — without the wrapper, reads
 * inside fn would be tracked to whoever called ``.value`` (the rendering
 * component), not to a cache-invalidator that this primitive could own.
 *
 * ```js
 * const total = memoizedDerived(
 *     (cart) => cart.items.reduce((s, x) => s + x.price * cart.discount[x.id], 0),
 *     [cart],
 * );
 * // Many reads in one render → fn runs once
 * total.value === total.value === total.value
 * // After cart.items.push(...) → next .value re-evaluates
 * ```
 *
 * **When to reach for ``memoizedDerived`` vs ``derived``**:
 *
 * - ``derived(fn)`` — fn is cheap or called once per render. No
 *   bookkeeping cost; matches Solid ``createMemo`` accessed-once-per-tick
 *   intuition.
 * - ``memoizedDerived(fn, deps)`` — fn is expensive (iterates collections,
 *   formats large datasets, walks nested structure) AND ``.value`` is read
 *   multiple times per render (template repeats, child component props,
 *   downstream getters). Matches Vue 3 ``computed`` / Svelte 5 ``$derived``
 *   semantics (always cached, auto-invalidated by dep tracking).
 *
 * **Why deps are explicit instead of auto-tracked**: OWL's
 * ``reactive(target, cb)`` binds ``cb`` at proxy-creation time. There is
 * no execution-context hook to say "run fn() and bind any reactive reads
 * inside it to my invalidator." The explicit-deps shape is the same
 * trade-off {@link effect} makes and for the same reason.
 *
 * **Read-path tracking**: only properties actually read inside fn on the
 * latest evaluation register subscriptions. If fn takes a branch
 * (``cond ? a.x : b.y``), mutating the un-read branch does not invalidate
 * — same semantics as ``effect``, verified by tests
 * ``"branch-dep read"`` and ``"branch-switch"`` in
 * ``reactive.test.js``.
 *
 * **Same-value writes don't invalidate**: OWL's set trap compares
 * ``originalValue !== Reflect.get(...)`` before notifying, so
 * ``store.n = store.n`` is a no-op for memoized consumers.
 *
 * **No async support**: fn must be synchronous. Async derivation belongs
 * in a service with its own caching policy.
 *
 * @template T
 * @template {object[]} D
 * @param {(...args: [...D]) => T} fn lazy thunk producing the derived
 *   value. Receives the reactive-wrapped ``deps`` as positional args so
 *   reads through them are tracked by the invalidator.
 * @param {[...D]} deps the reactive objects fn depends on (records,
 *   stores, plain reactive proxies). Same constraint as {@link effect}.
 * @returns {{ readonly value: T }}
 */
export function memoizedDerived(fn, deps) {
    /** @type {T} */
    let cached;
    let dirty = true;
    const reactiveDeps = reactive(deps, () => {
        dirty = true;
    });
    return {
        get value() {
            if (dirty) {
                cached = fn(...reactiveDeps);
                dirty = false;
            }
            return cached;
        },
    };
}
