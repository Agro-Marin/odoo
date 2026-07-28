// @ts-check
/** @odoo-module native */

/** @module @web/core/position/position_hook - OWL hook for auto-repositioning a popper element relative to a target */

import {
    EventBus,
    onWillDestroy,
    useChildSubEnv,
    useComponent,
    useEffect,
    useRef,
} from "@odoo/owl";
import { reposition } from "@web/core/position/utils";
import { omit } from "@web/core/utils/collections/objects";
import { useThrottleForAnimation } from "@web/core/utils/timing";

/** @import { ComputePositionOptions, PositioningSolution } from "@web/core/position/utils" */

/**
 * @typedef {Object} UsePositionOptionsExtensionType
 * @property {(popperElement: HTMLElement, solution: PositioningSolution) => void} [onPositioned]
 *  callback called when the positioning is done.
 * @typedef {ComputePositionOptions & UsePositionOptionsExtensionType} UsePositionOptions
 *
 * @typedef PositioningControl
 * @property {() => void} lock prevents further positioning updates
 * @property {() => void} unlock allows further positioning updates (triggers an update right away)
 */

export const POSITION_BUS = Symbol("position-bus");

/**
 * Makes sure that the `popper` element is always
 * placed at `position` from the `target` element.
 * If doing so the `popper` element is clipped off `container`,
 * sensible fallback positions are tried.
 * If all of fallback positions are also clipped off `container`,
 * the original position is used.
 *
 * Note: The popper element should be indicated in your template
 *       with a t-ref reference matching the refName argument.
 *
 * @param {string} refName
 *  name of the reference to the popper element in the template.
 * @param {() => HTMLElement} getTarget
 * @param {UsePositionOptions} [options={}] the options to be used for positioning
 * @returns {PositioningControl}
 *  control object to lock/unlock the positioning.
 */
export function usePosition(refName, getTarget, options = {}) {
    const ref = useRef(refName);
    let lock = false;
    /** @type {ComputePositionOptions["position"]} */
    let lastPosition;
    let lastRequestedPosition = options.position;
    const update = () => {
        const targetEl = getTarget();
        if (!ref.el || !targetEl?.isConnected || lock) {
            return;
        }
        if (options.position !== lastRequestedPosition) {
            lastRequestedPosition = options.position;
            lastPosition = undefined;
        }
        const repositionOptions = omit(options, "onPositioned");
        if (lastPosition) {
            repositionOptions.position = lastPosition;
        }
        const solution = reposition(ref.el, targetEl, repositionOptions);
        lastPosition = /** @type {ComputePositionOptions["position"]} */ (
            `${solution.direction}-${solution.variant}`
        );
        options.onPositioned?.(ref.el, solution);
    };

    const component = useComponent();
    const bus = /** @type {any} */ (component.env)[POSITION_BUS] || new EventBus();

    let executingUpdate = false;
    /**
     * The flag coalesces every trigger raised within one microtask into a
     * single `update()`. It is cleared in a `finally` because anything that
     * throws inside `update()` — `reposition`, or the caller's own
     * `onPositioned`, which reaches into the DOM (see `Popover.updateArrow`) —
     * would otherwise leave it stuck on, and this popper would silently stop
     * repositioning on scroll, resize, content change and unlock for the rest
     * of its life. The error still surfaces; only the freeze is prevented.
     */
    const batchedUpdate = async () => {
        if (executingUpdate) {
            return;
        }
        executingUpdate = true;
        try {
            update();
            await Promise.resolve();
        } finally {
            executingUpdate = false;
        }
    };
    bus.addEventListener("update", batchedUpdate);
    onWillDestroy(() => bus.removeEventListener("update", batchedUpdate));

    const isTopmost = !(POSITION_BUS in component.env);
    if (isTopmost) {
        useChildSubEnv({ [POSITION_BUS]: bus });
    }

    // Repositioning runs on EVERY patch — the popper's own size, and the
    // target's, can change without either element being replaced.
    useEffect(() => {
        bus.trigger("update");
    });

    if (isTopmost) {
        const throttledUpdate = useThrottleForAnimation(() => bus.trigger("update"));
        const scrollListener = (/** @type {Event} */ e) => {
            if (ref.el?.contains(/** @type {Node} */ (e.target))) {
                return;
            }
            throttledUpdate();
        };
        // Bound in its OWN effect, keyed on the document(s) it attaches to,
        // rather than sharing the unconditional one above. These listeners
        // depend only on which document owns the target, so re-binding them per
        // patch was pure churn: measured at 2 capture-phase document listeners
        // torn down and re-added on every render of the owning component (12
        // added / 10 removed across 5 renders), plus the window resize handler
        // — on a dropdown that re-renders per keystroke.
        useEffect(
            (targetDocument) => {
                if (!targetDocument) {
                    return;
                }
                /** @type {Document[]} */
                const documents = [targetDocument];
                if (
                    targetDocument.defaultView?.top &&
                    targetDocument.defaultView.top !== targetDocument.defaultView
                ) {
                    try {
                        documents.push(targetDocument.defaultView.top.document);
                    } catch {
                        // Don't access the top document if it is not allowed.
                        // (i.e. iframe origin or sandbox restriction)
                    }
                }
                for (const doc of documents) {
                    doc.addEventListener("scroll", scrollListener, { capture: true });
                    doc.addEventListener("load", throttledUpdate, { capture: true });
                }
                window.addEventListener("resize", throttledUpdate);
                return () => {
                    for (const doc of documents) {
                        doc.removeEventListener("scroll", scrollListener, {
                            capture: true,
                        });
                        doc.removeEventListener("load", throttledUpdate, {
                            capture: true,
                        });
                    }
                    window.removeEventListener("resize", throttledUpdate);
                };
            },
            () => [getTarget()?.ownerDocument],
        );
    }

    return {
        lock: () => {
            lock = true;
        },
        unlock: () => {
            lock = false;
            bus.trigger("update");
        },
    };
}
