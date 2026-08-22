/** @odoo-module native */
import { ancestors } from "@html_editor/utils/dom_traversal";
import { useComponent, useEffect } from "@odoo/owl";
import { couldBeScrollableX, couldBeScrollableY } from "@web/core/utils/dom/scrolling";
import { throttleForAnimation } from "@web/core/utils/timing";

export function usePositionHook(containerRef, document, callback) {
    const comp = useComponent();
    const onLayoutGeometryChange = throttleForAnimation(callback.bind(comp));
    const resizeObserver = new ResizeObserver(onLayoutGeometryChange);
    const cleanups = [];
    const addDomListener = (target, eventName, capture) => {
        target.addEventListener(eventName, onLayoutGeometryChange, capture);
        cleanups.push(() =>
            target.removeEventListener(eventName, onLayoutGeometryChange, capture),
        );
    };
    useEffect(
        () => {
            if (containerRef.el) {
                resizeObserver.observe(document.body);
                resizeObserver.observe(containerRef.el);
                addDomListener(window, "resize");
                if (document.defaultView !== window) {
                    addDomListener(document.defaultView, "resize");
                }
                addDomListener(document, "scroll");
                const scrollableElements = [
                    containerRef.el,
                    ...ancestors(containerRef.el),
                ].filter(
                    (node) => couldBeScrollableX(node) || couldBeScrollableY(node),
                );
                for (const scrollableElement of scrollableElements) {
                    addDomListener(scrollableElement, "scroll");
                    resizeObserver.observe(scrollableElement);
                }
            }
            return () => {
                resizeObserver.disconnect();
                for (const cleanup of cleanups.toReversed()) {
                    cleanup();
                    cleanups.pop();
                }
            };
        },
        () => [containerRef.el],
    );
}
