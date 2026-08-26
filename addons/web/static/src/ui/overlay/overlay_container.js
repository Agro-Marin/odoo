// @ts-check
/** @odoo-module native */

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
import { rootIdOf } from "@web/ui/overlay/root_id";

export const OVERLAY_SYMBOL = Symbol("Overlay");

export const DEFAULT_OVERLAY_SEQUENCE = 50;

const OVERLAY_ITEMS = Symbol("OverlayItems");

/**
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
    static serviceName = "overlay";
    static props = {
        overlays: { type: Object, optional: true },
        rootId: { type: String, optional: true },
    };

    setup() {
        this.root = useRef("root");
        this.state = useState({ rootId: this.props.rootId });
        this.overlays = useState(this.props.overlays ?? this.serviceOverlays);
        useChildSubEnv({ [OVERLAY_ITEMS]: [] });
        if (!this.props.rootId) {
            useEffect(
                () => {
                    this.state.rootId = rootIdOf(this.root.el);
                },
                () => [this.root.el],
            );
        }
    }

    /**
     * @returns {Record<number, any>}
     */
    get serviceOverlays() {
        const { name, serviceName } = /** @type {any} */ (this.constructor);
        // eslint-disable-next-line no-restricted-syntax
        const service = this.env.services[serviceName];
        if (!service) {
            throw new Error(
                `${name}.serviceName is "${serviceName}", but no such service is started in this env. ` +
                    `Pass an \`overlays\` prop, or start the service.`,
            );
        }
        return service.overlays;
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
