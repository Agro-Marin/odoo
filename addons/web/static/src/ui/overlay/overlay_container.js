// @ts-check
/** @odoo-module native */

/** @module @web/ui/overlay/overlay_container */

import {
    Component,
    onWillDestroy,
    useChildSubEnv,
    useComponent,
    useEffect,
    useRef,
    useState,
} from "@odoo/owl";
import { reportUncaught } from "@web/core/errors/error_utils";
import { sortBy } from "@web/core/utils/collections/arrays";
import { ErrorHandler } from "@web/core/utils/components";

export const OVERLAY_SYMBOL = Symbol("Overlay");

/**
 * Where an overlay lands in the stack when its caller names no sequence. Owned
 * here and imported by `overlay_service`, which is the only writer: two copies
 * of the number meant the stacking order the container compares by could
 * silently stop matching the one the service assigns.
 */
export const DEFAULT_OVERLAY_SEQUENCE = 50;

const OVERLAY_ITEMS = Symbol("OverlayItems");

/**
 * Gives descendants `baseEnv` extended with `extension`, where `baseEnv`
 * replaces the inherited environment rather than extending it.
 *
 * Owl has no API for replacing it, so this writes `childEnv` and then extends
 * it, in that order. Doing so in one call keeps the order from being an
 * unstated precondition of the caller: reversed, the extension is silently
 * dropped.
 *
 * @param {object | undefined} baseEnv
 * @param {object} extension
 */
function useHostedSubEnv(baseEnv, extension) {
    if (baseEnv) {
        /** @type {any} */ (useComponent()).__owl__.childEnv = baseEnv;
    }
    useChildSubEnv(extension);
}

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

        this.siblings = /** @type {OverlayItem[]} */ (
            /** @type {Record<symbol, any>} */ (this.env)[OVERLAY_ITEMS]
        );
        this.siblings.push(this);
        onWillDestroy(() => {
            const index = this.siblings.indexOf(this);
            if (index >= 0) {
                this.siblings.splice(index, 1);
            }
        });

        useHostedSubEnv(this.props.env, {
            [OVERLAY_SYMBOL]: {
                contains: (/** @type {EventTarget} */ target) => this.contains(target),
            },
        });
    }

    /** @returns {number} */
    get stackSequence() {
        return this.props.sequence ?? DEFAULT_OVERLAY_SEQUENCE;
    }

    /** @returns {number} */
    get stackId() {
        return this.props.id ?? 0;
    }

    /**
     * @param {OverlayItem} other
     * @returns {boolean}
     */
    isAtOrBelow(other) {
        const sequence = this.stackSequence;
        const otherSequence = other.stackSequence;
        return (
            otherSequence > sequence ||
            (otherSequence === sequence && other.stackId >= this.stackId)
        );
    }

    /**
     * @param {EventTarget} target
     * @returns {boolean}
     */
    contains(target) {
        const node = /** @type {Node} */ (target);
        return this.siblings.some(
            (oi) => this.isAtOrBelow(oi) && oi.rootRef.el?.contains(node),
        );
    }
}

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
        reportUncaught(error);
    }
}
