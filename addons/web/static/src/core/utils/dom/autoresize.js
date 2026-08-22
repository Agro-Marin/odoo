// @ts-check
/** @odoo-module native */

import { useEffect } from "@odoo/owl";

/**
 * @param {{ el: HTMLInputElement | HTMLTextAreaElement | null }} ref
 * @param {{ ignoreIfEmpty?: boolean, onResize?: (el: HTMLInputElement | HTMLTextAreaElement, options: object) => void, offset?: number, minimumHeight?: number }} [options]
 */
export function useAutoresize(ref, options = {}) {
    let wasProgrammaticallyResized = false;
    /** @type {((programmaticResize?: boolean) => void) | null} */
    let resize = null;
    useEffect(
        (el) => {
            if (el) {
                resize = (programmaticResize = false) => {
                    wasProgrammaticallyResized = programmaticResize;
                    if (options.ignoreIfEmpty && !el.value) {
                        return;
                    }
                    if (el instanceof HTMLInputElement) {
                        resizeInput(el, options);
                    } else {
                        resizeTextArea(
                            /** @type {HTMLTextAreaElement} */ (el),
                            options,
                        );
                    }
                    options.onResize?.(el, options);
                };
                const inputHandler = () => resize?.(true);
                el.addEventListener("input", inputHandler);
                const resizeObserver = new ResizeObserver(() => {
                    if (wasProgrammaticallyResized) {
                        wasProgrammaticallyResized = false;
                        return;
                    }
                    resize?.(true);
                });
                resizeObserver.observe(el);
                return () => {
                    el.removeEventListener("input", inputHandler);
                    resizeObserver.unobserve(el);
                    resizeObserver.disconnect();
                    resize = null;
                };
            }
        },
        () => [ref.el],
    );
    useEffect(() => {
        if (resize) {
            resize(true);
        }
    });
}

const TEXT_METRIC_PROPERTIES = [
    "font-family",
    "font-size",
    "font-style",
    "font-weight",
    "font-stretch",
    "font-variant",
    "font-variant-numeric",
    "letter-spacing",
    "text-transform",
    "word-spacing",
    "text-indent",
];

/**
 * @param {HTMLInputElement} input
 * @returns {number}
 */
function measureTextWidth(input) {
    const span = document.createElement("span");
    span.style.position = "absolute";
    span.style.visibility = "hidden";
    span.style.whiteSpace = "pre";
    const inputStyle = window.getComputedStyle(input);
    for (const property of TEXT_METRIC_PROPERTIES) {
        span.style.setProperty(property, inputStyle.getPropertyValue(property));
    }
    span.textContent = input.value;
    const container = input.parentNode || document.body;
    container.appendChild(span);
    const width = span.offsetWidth;
    span.remove();
    return width;
}

/**
 * @param {HTMLInputElement} input
 * @returns {number}
 */
export function boxExtraWidth(input) {
    const style = window.getComputedStyle(input);
    if (style.boxSizing !== "border-box") {
        return 0;
    }
    return (
        parseFloat(style.paddingLeft) +
        parseFloat(style.paddingRight) +
        parseFloat(style.borderLeftWidth) +
        parseFloat(style.borderRightWidth)
    );
}

/**
 * @param {HTMLInputElement} input
 * @param {{ offset?: number }} [options]
 */
function resizeInput(input, options) {
    input.style.width = "100%";
    const maxWidth = input.clientWidth;
    if (input.value === "" && input.placeholder !== "") {
        input.style.width = "auto";
        return;
    }
    const textWidth = measureTextWidth(input);
    const width = textWidth + boxExtraWidth(input) + (options?.offset || 0);
    if (width > maxWidth) {
        input.style.width = "100%";
        return;
    }
    input.style.width = `${width}px`;
}

/**
 * @param {HTMLTextAreaElement} textarea
 * @param {{ minimumHeight?: number }} [options]
 */
export function resizeTextArea(textarea, options = {}) {
    const minimumHeight = options.minimumHeight || 0;
    let heightOffset = 0;
    const style = window.getComputedStyle(textarea);
    if (style.boxSizing === "border-box") {
        const paddingHeight =
            parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);
        const borderHeight =
            parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth);
        heightOffset = borderHeight + paddingHeight;
    }
    const previousStyle = {
        borderTopWidth: textarea.style.borderTopWidth,
        borderBottomWidth: textarea.style.borderBottomWidth,
        paddingTop: textarea.style.paddingTop,
        paddingBottom: textarea.style.paddingBottom,
    };
    Object.assign(textarea.style, {
        height: "auto",
        borderTopWidth: 0,
        borderBottomWidth: 0,
        paddingTop: 0,
        paddingBottom: 0,
    });
    const height = Math.max(minimumHeight, textarea.scrollHeight + heightOffset);
    Object.assign(textarea.style, previousStyle, { height: `${height}px` });
    if (textarea.parentElement) {
        textarea.parentElement.style.height = `${height}px`;
    }
}
