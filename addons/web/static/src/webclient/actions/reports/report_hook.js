// @ts-check
/** @odoo-module native */

import { useComponent, useEffect } from "@odoo/owl";

/**
 * @param {{ el: HTMLElement | null }} ref
 * @param {string | null} [selector]
 */
export function useEnrichWithActionLinks(ref, selector = null) {
    const comp = useComponent();
    useEffect(
        (element) => {
            if (element.matches("iframe")) {
                element.onload = () => enrich(comp, element, selector, true);
            } else {
                enrich(comp, element, selector);
            }
        },
        () => [ref.el],
    );
}

/**
 * @param {Record<string, any>} component
 * @param {Element} targetElement
 * @param {string | null} [selector]
 * @param {boolean} [isIFrame]
 */
export function enrich(component, targetElement, selector, isIFrame = false) {
    const frameDoc = isIFrame
        ? /** @type {HTMLIFrameElement} */ (targetElement).contentDocument
        : null;
    if (isIFrame && !frameDoc) {
        return;
    }
    const doc = frameDoc ?? window.document;
    /** @type {ParentNode} */
    const root = frameDoc ?? targetElement;

    /** @type {ParentNode[]} */
    const targets = [];
    if (selector) {
        targets.push(...root.querySelectorAll(selector));
    } else {
        targets.push(root);
    }

    for (const currentTarget of targets) {
        const elementsToWrap = currentTarget.querySelectorAll(
            "[res-id][res-model][view-type]",
        );
        for (const element of elementsToWrap.values()) {
            const parent = element.parentNode;
            if (!parent || element.parentElement?.dataset.oActionLink === "1") {
                continue;
            }
            const wrapper = doc.createElement("a");
            wrapper.setAttribute("href", "#");
            wrapper.dataset.oActionLink = "1";
            wrapper.addEventListener("click", (ev) => {
                ev.preventDefault();
                const viewIdAttr = element.getAttribute("view-id");
                const viewId = viewIdAttr ? Number(viewIdAttr) : false;
                // eslint-disable-next-line no-restricted-syntax
                component.env.services.action.doAction({
                    type: "ir.actions.act_window",
                    view_mode: element.getAttribute("view-type"),
                    res_id: Number(element.getAttribute("res-id")),
                    res_model: element.getAttribute("res-model"),
                    views: [[viewId, element.getAttribute("view-type")]],
                });
            });
            parent.insertBefore(wrapper, element);
            wrapper.appendChild(element);
        }
    }
}
