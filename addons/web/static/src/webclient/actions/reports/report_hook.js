// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/reports/report_hook - Hook enriching DOM elements with [res-id][res-model] into clickable action links */

import { useComponent, useEffect } from "@odoo/owl";

/**
 * Enrich DOM elements with `[res-id][res-model][view-type]` attrs into
 * clickable action links. Iframe-aware (waits for `onload`).
 *
 * @param {{ el: HTMLElement | null }} ref - Owl ref to the element to enrich
 * @param {string | null} [selector] - Selector to apply to the element resolved by the ref
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
 * Wrap every `[res-id][res-model][view-type]` element under `targetElement` in
 * an anchor that opens the record.
 *
 * Exported for tests: the second pass this must be idempotent against is
 * driven by an iframe `onload`, which a unit test cannot provoke without
 * standing up a real frame — calling this twice is the same code path.
 *
 * @param {Object} component
 * @param {Element} targetElement
 * @param {string | null} [selector]
 * @param {boolean} [isIFrame]
 */
export function enrich(component, targetElement, selector, isIFrame = false) {
    let doc = window.document;

    if (isIFrame) {
        targetElement = targetElement.contentDocument;
        doc = targetElement;
    }

    const targets = [];
    if (selector) {
        targets.push(...targetElement.querySelectorAll(selector));
    } else {
        targets.push(targetElement);
    }

    for (const currentTarget of targets) {
        const elementsToWrap = currentTarget.querySelectorAll(
            "[res-id][res-model][view-type]",
        );
        for (const element of elementsToWrap.values()) {
            // Wrapping does not stop an element matching the selector, so a
            // second pass over the same DOM nests another anchor around it (and
            // another click listener). The iframe branch above re-runs enrich()
            // on every `onload`, i.e. on every navigation within the frame, so
            // this is a real second pass rather than a hypothetical one.
            if (element.parentElement?.dataset.oActionLink === "1") {
                continue;
            }
            const wrapper = doc.createElement("a");
            wrapper.setAttribute("href", "#");
            wrapper.dataset.oActionLink = "1";
            wrapper.addEventListener("click", (ev) => {
                ev.preventDefault();
                const viewIdAttr = element.getAttribute("view-id");
                const viewId = viewIdAttr ? Number(viewIdAttr) : false;
                component.env.services.action.doAction({
                    type: "ir.actions.act_window",
                    view_mode: element.getAttribute("view-type"),
                    res_id: Number(element.getAttribute("res-id")),
                    res_model: element.getAttribute("res-model"),
                    views: [[viewId, element.getAttribute("view-type")]],
                });
            });
            element.parentNode.insertBefore(wrapper, element);
            wrapper.appendChild(element);
        }
    }
}
