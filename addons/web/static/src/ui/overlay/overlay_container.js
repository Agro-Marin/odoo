// @ts-check
/** @odoo-module native */

/** @module @web/ui/overlay/overlay_container - Renders overlay entries (popovers, dialogs, effects) with nested click-away tracking */

import {
    Component,
    onWillDestroy,
    useChildSubEnv,
    useEffect,
    useRef,
    useState,
} from "@odoo/owl";
import { sortBy } from "@web/core/utils/collections/arrays";
import { ErrorHandler } from "@web/core/utils/components";
/** @type {OverlayItem[]} */
const OVERLAY_ITEMS = [];
export const OVERLAY_SYMBOL = Symbol("Overlay");

/**
 * Wrapper for a single overlay entry (popover, dialog, bottom sheet, etc.).
 *
 * Tracks itself in a global `OVERLAY_ITEMS` stack for nested click-away
 * containment checks. Injects an `OVERLAY_SYMBOL` into child env so
 * descendants can test whether a click target is "inside" the overlay tree.
 */
class OverlayItem extends Component {
    static template = "web.OverlayContainer.Item";
    static components = {};
    static props = {
        component: { type: Function },
        props: { type: Object },
        env: { type: Object, optional: true },
        // Stacking coordinates, forwarded from the overlay entry so containment
        // can order by z-order (sequence) rather than mount order. Optional for
        // any out-of-band renderer that constructs an OverlayItem directly.
        sequence: { type: Number, optional: true },
        id: { type: Number, optional: true },
    };

    setup() {
        this.rootRef = useRef("rootRef");

        OVERLAY_ITEMS.push(this);
        onWillDestroy(() => {
            const index = OVERLAY_ITEMS.indexOf(this);
            OVERLAY_ITEMS.splice(index, 1);
        });

        if (this.props.env) {
            this.__owl__.childEnv = this.props.env;
        }

        useChildSubEnv({
            [OVERLAY_SYMBOL]: {
                contains: (/** @type {EventTarget} */ target) => this.contains(target),
            },
        });
    }

    /** @returns {OverlayItem[]} this overlay and all overlays stacked above it */
    get subOverlays() {
        // Order by ascending (sequence, id) — the SAME ordering
        // OverlayContainer renders and the browser paints (z-order), NOT
        // OVERLAY_ITEMS insertion order. Insertion order is MOUNT order: an
        // overlay opened later but with a lower sequence mounts last yet renders
        // BELOW an earlier higher-sequence one, so a raw ``slice(indexOf(this))``
        // would mis-identify which overlays are "above me" and break click-away
        // containment. ``id`` (monotonic from the service) is a stable tiebreak
        // within one sequence.
        const ordered = [...OVERLAY_ITEMS].sort(
            (a, b) =>
                (a.props.sequence ?? 50) - (b.props.sequence ?? 50) ||
                (a.props.id ?? 0) - (b.props.id ?? 0),
        );
        return ordered.slice(ordered.indexOf(this));
    }

    /**
     * @param {EventTarget} target
     * @returns {boolean} whether target is inside this overlay or any sub-overlay
     */
    contains(target) {
        const node = /** @type {Node} */ (target);
        return (
            this.rootRef.el?.contains(node) ||
            this.subOverlays.some((oi) => oi.rootRef.el?.contains(node))
        );
    }
}

/** Renders all active overlays sorted by sequence, scoped to a shadow root. */
export class OverlayContainer extends Component {
    static template = "web.OverlayContainer";
    static components = { ErrorHandler, OverlayItem };
    static props = { overlays: { type: Object, optional: true } };

    setup() {
        this.root = useRef("root");
        this.state = useState({ rootEl: null });
        // Read the overlays from this env's overlay service (unless explicitly
        // given as props): each rendered container must show the overlays of
        // ITS OWN environment — see the registration in overlay_service. The
        // raw service (not useService) is intentional: this is a plain read of
        // the reactive `overlays` store, not a lifecycle-bound service handle.
        // eslint-disable-next-line no-restricted-syntax
        const overlays = this.props.overlays ?? this.env.services.overlay.overlays;
        this.overlays = useState(overlays);
        useEffect(
            () => {
                this.state.rootEl = this.root.el;
            },
            () => [this.root.el],
        );
    }

    /** @returns {Object[]} overlays sorted by ascending sequence */
    get sortedOverlays() {
        return sortBy(
            Object.values(/** @type {Record<string, any>} */ (this.overlays)),
            (overlay) => overlay.sequence,
        );
    }

    /**
     * @param {Record<string, any>} overlay
     * @returns {boolean} whether overlay belongs to this container's shadow root
     */
    isVisible(overlay) {
        return overlay.rootId === this.state.rootEl?.getRootNode()?.host?.id;
    }

    /**
     * @param {Record<string, any>} overlay
     * @param {Error} error
     */
    handleError(overlay, error) {
        overlay.remove();
        // Uses Promise.resolve().then() (not queueMicrotask) so the error routes
        // through the unhandledrejection handler → UncaughtPromiseError dialog.
        Promise.resolve().then(() => {
            throw error;
        });
    }
}
