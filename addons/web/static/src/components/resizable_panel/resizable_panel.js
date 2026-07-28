// @ts-check
/** @odoo-module native */

/** @module @web/components/resizable_panel/resizable_panel - Side panel component with drag handle for interactive width resizing */

import {
    Component,
    onMounted,
    onWillUnmount,
    onWillUpdateProps,
    useComponent,
    useExternalListener,
    useRef,
} from "@odoo/owl";

/**
 * @typedef {"start" | "end"} ResizeSide
 *
 * @typedef {Object} UseResizableParams
 * @property {string | import("@odoo/owl").Ref<HTMLElement>} containerRef - Ref name or ref object for the resizable container
 * @property {string | import("@odoo/owl").Ref<HTMLElement>} handleRef - Ref name or ref object for the drag handle
 * @property {number} [initialWidth=400] - Starting width in pixels
 * @property {(props: Object) => number} [getMinWidth] - Returns minimum width from current props
 * @property {(width: number) => void} [onResize] - Callback invoked after each resize with the new width
 * @property {(props: Object) => ResizeSide} [getResizeSide] - Returns which side the handle is on from current props
 */

/**
 * OWL composable hook that makes a container element resizable via a drag handle.
 * Handles pointer interactions (mouse, touch, and pen), respects RTL/LTR
 * direction, and clamps width between a minimum and the available parent width.
 *
 * @param {UseResizableParams} params
 */
function useResizable({
    containerRef: _containerRef,
    handleRef: _handleRef,
    initialWidth = 400,
    getMinWidth = (_props) => 400,
    onResize = (_width) => {},
    getResizeSide = (_props) => "end",
}) {
    /** @type {import("@odoo/owl").Ref<HTMLElement>} */
    const containerRef =
        typeof _containerRef == "string" ? useRef(_containerRef) : _containerRef;
    /** @type {import("@odoo/owl").Ref<HTMLElement>} */
    const handleRef = typeof _handleRef == "string" ? useRef(_handleRef) : _handleRef;
    const props = useComponent().props;

    let minWidth = getMinWidth(props);
    let resizeSide = getResizeSide(props);
    let isChangingSize = false;

    useExternalListener(window, "resize", () => {
        // `useRef().el` is null for an element that is not in the document, so
        // a panel detached while still mounted would throw here on the next
        // resize. Every other reader in this hook already guards; this one and
        // `resize` did not.
        if (!containerRef.el) {
            return;
        }
        const limit = getLimitWidth();
        if (getContainerRect().width >= limit) {
            resize(computeFinalWidth(limit));
        }
    });

    let docDirection;

    onMounted(() => {
        if (handleRef.el) {
            resize(clampWidth(initialWidth));
            handleRef.el.addEventListener("pointerdown", onPointerDown);
            handleRef.el.style.touchAction = "none";
        }
    });

    onWillUpdateProps((nextProps) => {
        minWidth = getMinWidth(nextProps);
        resizeSide = getResizeSide(nextProps);
    });

    onWillUnmount(() => {
        if (handleRef.el) {
            handleRef.el.removeEventListener("pointerdown", onPointerDown);
        }
        if (isChangingSize) {
            onPointerUp();
        }
    });

    /**
     * Begin drag — disable pointer events and text selection on body.
     * The document-level drag listeners are only attached for the
     * duration of the drag. Pointer events (vs mouse events) make the
     * handle usable with touch and pen too; capturing the pointer keeps
     * the move/up stream flowing to the handle (and bubbling to the
     * document listeners below) even when the pointer leaves it.
     *
     * @param {PointerEvent} ev
     */
    function onPointerDown(ev) {
        isChangingSize = true;
        // Read the direction per drag rather than caching it from a mount-time
        // effect: that made correctness depend on hook registration order (the
        // effect had to be registered before the onMounted that resizes), and
        // it never picked up a direction flipped after mount.
        if (containerRef.el) {
            docDirection = getComputedStyle(containerRef.el).direction;
        }
        document.body.classList.add("pe-none", "user-select-none");
        try {
            handleRef.el?.setPointerCapture(ev.pointerId);
        } catch {
            // Synthetic events (tests) have no active pointer to capture.
        }
        document.addEventListener("pointermove", onPointerMove);
        document.addEventListener("pointerup", onPointerUp);
        document.addEventListener("pointercancel", onPointerUp);
    }

    /** End drag — restore pointer events and text selection on body. */
    function onPointerUp() {
        isChangingSize = false;
        document.body.classList.remove("pe-none", "user-select-none");
        document.removeEventListener("pointermove", onPointerMove);
        document.removeEventListener("pointerup", onPointerUp);
        document.removeEventListener("pointercancel", onPointerUp);
    }

    /**
     * Handle drag movement — compute new width from cursor position,
     * accounting for RTL/LTR direction and resize side.
     *
     * @param {PointerEvent} ev
     */
    function onPointerMove(ev) {
        if (!isChangingSize || !containerRef.el) {
            return;
        }
        const direction =
            (docDirection === "ltr" && resizeSide === "end") ||
            (docDirection === "rtl" && resizeSide === "start")
                ? 1
                : -1;
        const fixedSide = direction === 1 ? "left" : "right";
        const containerRect = getContainerRect();
        const newWidth = (ev.clientX - containerRect[fixedSide]) * direction;
        resize(computeFinalWidth(newWidth));
    }

    /** @returns {number} half the handle's width, the gap it needs to stay grabbable */
    function getHandlerSpacing() {
        return handleRef.el ? handleRef.el.offsetWidth / 2 : 10;
    }

    /**
     * Clamp a width between the minimum width and the available parent space.
     *
     * @param {number} width - desired container width in pixels
     * @returns {number} clamped width in pixels
     */
    function clampWidth(width) {
        return Math.min(
            Math.max(minWidth, width),
            getLimitWidth() - getHandlerSpacing(),
        );
    }

    /**
     * Clamp a drag target, offsetting it by the handle spacing so the handle
     * stays under the cursor.
     *
     * @param {number} targetContainerWidth - desired container width in pixels
     * @returns {number} clamped width in pixels
     */
    function computeFinalWidth(targetContainerWidth) {
        return clampWidth(targetContainerWidth + getHandlerSpacing());
    }

    /**
     * Get the container's positional rect in viewport coordinates -- the same
     * space as `PointerEvent.clientX`, which `onPointerMove` subtracts it from.
     *
     * @returns {{ left: number, right: number, width: number }}
     */
    function getContainerRect() {
        return containerRef.el.getBoundingClientRect();
    }

    /**
     * Get the maximum available width from the offset parent, or the window.
     *
     * @returns {number} maximum width in pixels
     */
    function getLimitWidth() {
        const offsetParent = /** @type {HTMLElement | null} */ (
            containerRef.el.offsetParent
        );
        return offsetParent ? offsetParent.offsetWidth : window.innerWidth;
    }

    /**
     * Apply the given width to the container element and notify via callback.
     *
     * @param {number} width - new width in pixels
     */
    function resize(width) {
        if (!containerRef.el) {
            return;
        }
        containerRef.el.style.setProperty("width", `${width}px`);
        onResize(width);
    }
}

/**
 * Side panel OWL component with a drag handle for interactive width resizing.
 * Wraps the `useResizable` hook with declarative props.
 */
export class ResizablePanel extends Component {
    static template = "web.ResizablePanel";

    static components = {};
    static props = {
        onResize: { type: Function, optional: true },
        initialWidth: { type: Number, optional: true },
        minWidth: { type: Number, optional: true },
        class: { type: String, optional: true },
        slots: { type: Object },
        handleSide: {
            validate: (val) => ["start", "end"].includes(val),
            optional: true,
        },
    };
    static defaultProps = {
        onResize: () => {},
        initialWidth: 400,
        minWidth: 400,
        class: "",
        handleSide: "end",
    };

    /** Wire up the resizable hook with prop-driven configuration. */
    setup() {
        useResizable({
            containerRef: "containerRef",
            handleRef: "handleRef",
            onResize: this.props.onResize,
            initialWidth: this.props.initialWidth,
            getMinWidth: (props) => props.minWidth,
            getResizeSide: (props) => props.handleSide,
        });
    }

    /**
     * Compute CSS classes, adding `position-relative` if no position class is present.
     *
     * @returns {string} space-separated class string
     */
    get class() {
        const classes = this.props.class.split(" ");
        if (!classes.some((cls) => cls.startsWith("position-"))) {
            classes.push("position-relative");
        }
        return classes.join(" ");
    }
}
