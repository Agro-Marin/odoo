/** @odoo-module native */
import { useRef } from "@odoo/owl";
import { useMountedListener } from "@web/core/utils/hooks";
import { useListener } from "@web/core/utils/owl_bridge";

/**
 * @param {string} targetRefName
 * @param {number} [minHeight]
 * @returns {Function}
 */
export function useResizer(targetRefName, minHeight = 100) {
    const targetRef = useRef(targetRefName);
    let isMouseDownOnResizer = false;
    let startOffsetTop, startHeight;
    const onResizerMouseDown = (ev) => {
        isMouseDownOnResizer = true;
        startHeight = targetRef.el.offsetHeight;
        startOffsetTop = ev.pageY;
    };
    useMountedListener(document, "mousemove", (ev) => {
        if (isMouseDownOnResizer) {
            const offsetTop = ev.pageY - startOffsetTop;
            const newHeight = Math.max(startHeight + offsetTop, minHeight);
            targetRef.el.style.height = `${newHeight}px`;
        }
    });
    useListener(document, "mouseup", () => (isMouseDownOnResizer = false));
    return onResizerMouseDown;
}
