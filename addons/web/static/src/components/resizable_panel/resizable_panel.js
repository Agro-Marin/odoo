// @ts-check
/** @odoo-module native */

/** @module @web/components/resizable_panel/resizable_panel */

import {
    Component,
    onMounted,
    onWillUnmount,
    onWillUpdateProps,
    useComponent,
    useExternalListener,
    useRef,
} from "@odoo/owl";
import { useThrottleForAnimation } from "@web/core/utils/timing";

/**
 * @typedef {"start" | "end"} ResizeSide
 * @typedef {Object} UseResizableParams
 * @property {string | import("@odoo/owl").Ref<HTMLElement>} containerRef
 * @property {string | import("@odoo/owl").Ref<HTMLElement>} handleRef
 * @property {(props: Object) => number} [getInitialWidth]
 * @property {(props: Object) => number} [getMinWidth]
 * @property {(width: number) => void} [onResize]
 * @property {(props: Object) => ResizeSide} [getResizeSide]
 */

/**
 * @param {UseResizableParams} params
 */
function useResizable({
    containerRef: _containerRef,
    handleRef: _handleRef,
    getInitialWidth = (_props) => 400,
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
    let initialWidth = getInitialWidth(props);
    let isChangingSize = false;

    // Resizing fires far faster than the screen refreshes, and each call
    // measures the container and its offset parent before writing a width back.
    const onWindowResize = useThrottleForAnimation(() => {
        if (!containerRef.el) {
            return;
        }
        const limit = getLimitWidth();
        if (getContainerRect().width >= limit) {
            resize(computeFinalWidth(limit));
        }
    });
    useExternalListener(window, "resize", onWindowResize);

    let docDirection;

    onMounted(() => {
        if (handleRef.el) {
            resize(clampWidth(initialWidth));
            handleRef.el.addEventListener("pointerdown", onPointerDown);
            handleRef.el.style.touchAction = "none";
        }
    });

    onWillUpdateProps((nextProps) => {
        const previousInitialWidth = initialWidth;
        minWidth = getMinWidth(nextProps);
        resizeSide = getResizeSide(nextProps);
        initialWidth = getInitialWidth(nextProps);
        const currentWidth = getCurrentWidth();
        const nextWidth = clampWidth(
            initialWidth !== previousInitialWidth ? initialWidth : currentWidth,
        );
        if (nextWidth !== currentWidth) {
            resize(nextWidth);
        }
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
     * @param {PointerEvent} ev
     */
    function onPointerDown(ev) {
        isChangingSize = true;
        if (containerRef.el) {
            docDirection = getComputedStyle(containerRef.el).direction;
        }
        document.body.classList.add("pe-none", "user-select-none");
        try {
            handleRef.el?.setPointerCapture(ev.pointerId);
        } catch {}
        document.addEventListener("pointermove", onPointerMove);
        document.addEventListener("pointerup", onPointerUp);
        document.addEventListener("pointercancel", onPointerUp);
    }

    function onPointerUp() {
        isChangingSize = false;
        document.body.classList.remove("pe-none", "user-select-none");
        document.removeEventListener("pointermove", onPointerMove);
        document.removeEventListener("pointerup", onPointerUp);
        document.removeEventListener("pointercancel", onPointerUp);
    }

    /**
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

    /** @returns {number} */
    function getHandlerSpacing() {
        return handleRef.el ? handleRef.el.offsetWidth / 2 : 10;
    }

    /**
     * @param {number} width
     * @returns {number}
     */
    function clampWidth(width) {
        return Math.min(
            Math.max(minWidth, width),
            getLimitWidth() - getHandlerSpacing(),
        );
    }

    /**
     * @param {number} targetContainerWidth
     * @returns {number}
     */
    function computeFinalWidth(targetContainerWidth) {
        return clampWidth(targetContainerWidth + getHandlerSpacing());
    }

    /**
     * @returns {{ left: number, right: number, width: number }}
     */
    function getContainerRect() {
        return /** @type {HTMLElement} */ (containerRef.el).getBoundingClientRect();
    }

    /**
     * @returns {number}
     */
    function getCurrentWidth() {
        const styled = Number.parseFloat(containerRef.el?.style.width ?? "");
        if (Number.isFinite(styled)) {
            return styled;
        }
        return containerRef.el ? getContainerRect().width : initialWidth;
    }

    /**
     * @returns {number}
     */
    function getLimitWidth() {
        // The container is measured through its offset parent, and both can be
        // absent: `onWillUpdateProps` runs whenever the owner re-renders, which
        // includes renders where this panel is not laid out -- detached, or
        // `display: none`, both of which null the offset parent, and the ref
        // itself is null until the first patch. "Cannot measure a parent" and
        // "cannot measure at all" deserve the same answer, so both fall back to
        // the viewport rather than throwing; every other accessor here already
        // tolerates a null ref, and `resize` no-ops on one.
        const offsetParent = /** @type {HTMLElement | null} */ (
            containerRef.el?.offsetParent ?? null
        );
        return offsetParent ? offsetParent.offsetWidth : window.innerWidth;
    }

    /**
     * @param {number} width
     */
    function resize(width) {
        if (!containerRef.el) {
            return;
        }
        containerRef.el.style.setProperty("width", `${width}px`);
        onResize(width);
    }
}

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

    setup() {
        useResizable({
            containerRef: "containerRef",
            handleRef: "handleRef",
            onResize: this.props.onResize,
            getInitialWidth: (props) => props.initialWidth,
            getMinWidth: (props) => props.minWidth,
            getResizeSide: (props) => props.handleSide,
        });
    }

    /**
     * @returns {string}
     */
    get class() {
        const classes = this.props.class.split(" ");
        if (!classes.some((cls) => cls.startsWith("position-"))) {
            classes.push("position-relative");
        }
        return classes.join(" ");
    }
}
