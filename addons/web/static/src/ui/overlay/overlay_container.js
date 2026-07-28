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

export const OVERLAY_SYMBOL = Symbol("Overlay");

/**
 * Env key holding the stack of `OverlayItem`s belonging to one
 * `OverlayContainer`. Scoped per container rather than module-global: several
 * containers coexist (main document plus one per shadow root), and an overlay
 * in one root is not "inside" an overlay in another, so mixing their stacks
 * would keep click-away from closing unrelated popovers.
 */
const OVERLAY_ITEMS = Symbol("OverlayItems");

/**
 * Wrapper for a single overlay entry (popover, dialog, bottom sheet, etc.).
 *
 * Registers itself in its container's stack for nested click-away containment
 * checks. Injects an `OVERLAY_SYMBOL` into child env so descendants can test
 * whether a click target is "inside" the overlay tree.
 */
class OverlayItem extends Component {
    static template = "web.OverlayContainer.Item";
    static props = {
        component: { type: Function },
        props: { type: Object },
        env: { type: Object, optional: true },
        sequence: { type: Number, optional: true },
        id: { type: Number, optional: true },
    };

    setup() {
        this.rootRef = useRef("rootRef");

        this.siblings = /** @type {OverlayItem[]} */ (this.env[OVERLAY_ITEMS]);
        this.siblings.push(this);
        onWillDestroy(() => {
            const index = this.siblings.indexOf(this);
            if (index >= 0) {
                this.siblings.splice(index, 1);
            }
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

    /** @returns {[number, number]} stacking key: sequence first, then insertion id */
    get stackKey() {
        return [this.props.sequence ?? 50, this.props.id ?? 0];
    }

    /**
     * This overlay and all overlays stacked above it. Every click-away check
     * runs through here, so it stays a filter over the container's stack
     * rather than sorting a copy of it on each call.
     *
     * @returns {OverlayItem[]}
     */
    get subOverlays() {
        const [sequence, id] = this.stackKey;
        return this.siblings.filter((oi) => {
            const [otherSequence, otherId] = oi.stackKey;
            return (
                otherSequence > sequence ||
                (otherSequence === sequence && otherId >= id)
            );
        });
    }

    /**
     * @param {EventTarget} target
     * @returns {boolean} whether target is inside this overlay or any sub-overlay
     */
    contains(target) {
        const node = /** @type {Node} */ (target);
        return this.subOverlays.some((oi) => oi.rootRef.el?.contains(node));
    }
}

/** Renders all active overlays sorted by sequence, scoped to a shadow root. */
export class OverlayContainer extends Component {
    static template = "web.OverlayContainer";
    static components = { ErrorHandler, OverlayItem };
    static props = {
        overlays: { type: Object, optional: true },
        rootId: { type: String, optional: true },
    };

    setup() {
        this.root = useRef("root");
        this.state = useState({ rootId: this.props.rootId });
        // eslint-disable-next-line no-restricted-syntax
        const overlays = this.props.overlays ?? this.env.services.overlay.overlays;
        this.overlays = useState(overlays);
        useChildSubEnv({ [OVERLAY_ITEMS]: [] });
        if (!this.props.rootId) {
            useEffect(
                () => {
                    this.state.rootId = /** @type {ShadowRoot} */ (
                        this.root.el?.getRootNode()
                    )?.host?.id;
                },
                () => [this.root.el],
            );
        }
    }

    /**
     * This container's own overlays, by ascending sequence.
     *
     * Filtered BEFORE sorting: every container on the page re-runs this on
     * each render, and a shadow-rooted one would otherwise sort the whole
     * cross-root set only to discard most of it.
     *
     * A container inside a shadow root should declare its `rootId` prop: until
     * the root element is mounted it cannot tell its own host id apart from
     * `undefined` (= the main document), and would mount every main-document
     * overlay for one frame before dropping it again.
     *
     * @returns {Object[]}
     */
    get sortedOverlays() {
        const { rootId } = this.state;
        const mine = Object.values(
            /** @type {Record<string, any>} */ (this.overlays),
        ).filter((overlay) => overlay.rootId === rootId);
        return sortBy(mine, (overlay) => overlay.sequence);
    }

    /**
     * @param {Record<string, any>} overlay
     * @param {Error} error
     */
    handleError(overlay, error) {
        overlay.remove();
        Promise.resolve().then(() => {
            throw error;
        });
    }
}
