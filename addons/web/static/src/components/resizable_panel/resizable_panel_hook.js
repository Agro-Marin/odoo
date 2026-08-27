// @ts-check
/** @odoo-module native */

import {
    onWillUnmount,
    onWillUpdateProps,
    useComponent,
    useEffect,
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
 * Drags one panel edge.
 *
 * The measurements all read from the live element rather than from state,
 * because the thing being resized is also being laid out by CSS: the offset
 * parent decides the ceiling, the handle's own width decides how close to it the
 * panel may get, and the container's `direction` decides which way a drag grows.
 */
class ResizeController {
    /**
     * @param {import("@odoo/owl").Ref<HTMLElement>} containerRef
     * @param {import("@odoo/owl").Ref<HTMLElement>} handleRef
     * @param {{ getMinWidth: Function, getResizeSide: Function, getInitialWidth: Function, onResize: Function }} params
     * @param {Object} props
     */
    constructor(containerRef, handleRef, params, props) {
        this.containerRef = containerRef;
        this.handleRef = handleRef;
        this.params = params;
        this.minWidth = params.getMinWidth(props);
        this.resizeSide = params.getResizeSide(props);
        this.initialWidth = params.getInitialWidth(props);
        this.isChangingSize = false;
        /** @type {string | undefined} */
        this.docDirection = undefined;
        this.onPointerDown = this.onPointerDown.bind(this);
        this.onPointerMove = this.onPointerMove.bind(this);
        this.onPointerUp = this.onPointerUp.bind(this);
    }

    /**
     * @param {Object} nextProps
     */
    applyProps(nextProps) {
        const previousInitialWidth = this.initialWidth;
        this.minWidth = this.params.getMinWidth(nextProps);
        this.resizeSide = this.params.getResizeSide(nextProps);
        this.initialWidth = this.params.getInitialWidth(nextProps);
        const currentWidth = this.currentWidth();
        // A changed initialWidth is an instruction; an unchanged one must not undo
        // a width the user dragged to.
        const nextWidth = this.clampWidth(
            this.initialWidth !== previousInitialWidth
                ? this.initialWidth
                : currentWidth,
        );
        if (nextWidth !== currentWidth) {
            this.resize(nextWidth);
        }
    }

    /**
     * @param {HTMLElement} handle
     * @returns {() => void} teardown
     */
    attach(handle) {
        this.resize(this.clampWidth(this.initialWidth));
        handle.addEventListener("pointerdown", this.onPointerDown);
        handle.style.touchAction = "none";
        return () => handle.removeEventListener("pointerdown", this.onPointerDown);
    }

    /** @param {PointerEvent} ev */
    onPointerDown(ev) {
        this.isChangingSize = true;
        if (this.containerRef.el) {
            this.docDirection = getComputedStyle(this.containerRef.el).direction;
        }
        document.body.classList.add("pe-none", "user-select-none");
        try {
            this.handleRef.el?.setPointerCapture(ev.pointerId);
        } catch {
            // No capture is survivable: the document-level listeners still fire.
        }
        document.addEventListener("pointermove", this.onPointerMove);
        document.addEventListener("pointerup", this.onPointerUp);
        document.addEventListener("pointercancel", this.onPointerUp);
    }

    onPointerUp() {
        this.isChangingSize = false;
        document.body.classList.remove("pe-none", "user-select-none");
        document.removeEventListener("pointermove", this.onPointerMove);
        document.removeEventListener("pointerup", this.onPointerUp);
        document.removeEventListener("pointercancel", this.onPointerUp);
    }

    /** @param {PointerEvent} ev */
    onPointerMove(ev) {
        if (!this.isChangingSize || !this.containerRef.el) {
            return;
        }
        const direction =
            (this.docDirection === "ltr" && this.resizeSide === "end") ||
            (this.docDirection === "rtl" && this.resizeSide === "start")
                ? 1
                : -1;
        const fixedSide = direction === 1 ? "left" : "right";
        const newWidth = (ev.clientX - this.containerRect()[fixedSide]) * direction;
        this.resize(this.finalWidth(newWidth));
    }

    onWindowResize() {
        if (!this.containerRef.el) {
            return;
        }
        const limit = this.limitWidth();
        if (this.containerRect().width >= limit) {
            this.resize(this.finalWidth(limit));
        }
    }

    /** @returns {number} half the handle, so the panel stops short of the edge */
    handlerSpacing() {
        return this.handleRef.el ? this.handleRef.el.offsetWidth / 2 : 10;
    }

    /**
     * @param {number} width
     * @returns {number}
     */
    clampWidth(width) {
        return Math.min(
            Math.max(this.minWidth, width),
            this.limitWidth() - this.handlerSpacing(),
        );
    }

    /**
     * @param {number} targetContainerWidth
     * @returns {number}
     */
    finalWidth(targetContainerWidth) {
        return this.clampWidth(targetContainerWidth + this.handlerSpacing());
    }

    /** @returns {{ left: number, right: number, width: number }} */
    containerRect() {
        return /** @type {HTMLElement} */ (
            this.containerRef.el
        ).getBoundingClientRect();
    }

    /** @returns {number} */
    currentWidth() {
        const styled = Number.parseFloat(this.containerRef.el?.style.width ?? "");
        if (Number.isFinite(styled)) {
            return styled;
        }
        return this.containerRef.el ? this.containerRect().width : this.initialWidth;
    }

    /** @returns {number} how wide the panel is allowed to get */
    limitWidth() {
        const offsetParent = /** @type {HTMLElement | null} */ (
            this.containerRef.el?.offsetParent ?? null
        );
        return offsetParent ? offsetParent.offsetWidth : window.innerWidth;
    }

    /** @param {number} width */
    resize(width) {
        if (!this.containerRef.el) {
            return;
        }
        this.containerRef.el.style.setProperty("width", `${width}px`);
        this.params.onResize(width);
    }
}

/**
 * @param {UseResizableParams} params
 */
export function useResizable({
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
    const component = useComponent();
    const controller = new ResizeController(
        containerRef,
        handleRef,
        { getInitialWidth, getMinWidth, onResize, getResizeSide },
        component.props,
    );

    useExternalListener(
        window,
        "resize",
        useThrottleForAnimation(() => controller.onWindowResize()),
    );

    // Keyed on the handle element, not on mount/unmount: bound in onMounted and
    // released in onWillUnmount, a handle replaced in between keeps the old
    // listener and the new one never gets one.
    useEffect(
        (el) => (el ? controller.attach(el) : undefined),
        () => [handleRef.el],
    );

    onWillUpdateProps((nextProps) => controller.applyProps(nextProps));

    onWillUnmount(() => {
        if (controller.isChangingSize) {
            controller.onPointerUp();
        }
    });
}
