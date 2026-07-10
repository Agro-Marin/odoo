// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/dom/autoresize - useAutoresize hook to auto-grow input/textarea elements on content change */

import { useEffect } from "@odoo/owl";

/**
 * Auto-resizes an input/textarea to fit its content on each update. Forces a
 * layout reflow on every update (mild perf cost). Textareas must be the sole
 * child of their parent div (see text_field).
 *
 * @param {{ el: HTMLInputElement | HTMLTextAreaElement | null }} ref
 * @param {{ ignoreIfEmpty?: boolean, onResize?: (el: HTMLInputElement | HTMLTextAreaElement, options: object) => void, offset?: number, minimumHeight?: number }} [options]
 */
export function useAutoresize(ref, options = {}) {
    let wasProgrammaticallyResized = false;
    /** @type {(programmaticResize?: boolean) => void} */
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
                const inputHandler = () => resize(true);
                el.addEventListener("input", inputHandler);
                const resizeObserver = new ResizeObserver(() => {
                    // Suppress the observer fire that follows our own style
                    // mutations, so we do not loop on a resize we just made.
                    if (wasProgrammaticallyResized) {
                        wasProgrammaticallyResized = false;
                        return;
                    }
                    // The resize() call below mutates styles and will itself
                    // trigger another observer fire — pass ``true`` so that
                    // follow-up fire is suppressed, otherwise the observer
                    // re-enters resize indefinitely (textareas in flex/grid
                    // parents oscillate by 1px and the loop never terminates).
                    resize(true);
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

/**
 * Measure text width via a hidden span in the input's parent, so it inherits
 * the same CSS context (font-variant-numeric, etc.) as the input. Input
 * scrollWidth can differ ~10px from span width in Chromium, causing visual
 * jumps between readonly/edit mode.
 *
 * @param {HTMLInputElement} input
 * @returns {number} the text width in pixels
 */
function measureTextWidth(input) {
    const span = document.createElement("span");
    span.style.position = "absolute";
    span.style.visibility = "hidden";
    span.style.whiteSpace = "nowrap";
    span.textContent = input.value;
    // Append to parent so it inherits the input's CSS context.
    const container = input.parentNode || document.body;
    container.appendChild(span);
    // Use offsetWidth (not getBoundingClientRect) to match how browser computes
    // integer pixel widths for offsetWidth on the readonly span counterpart.
    const width = span.offsetWidth;
    span.remove();
    return width;
}

/**
 * @param {HTMLInputElement} input
 * @param {{ offset?: number }} [options]
 */
function resizeInput(input, options) {
    // This mesures the maximum width of the input which can get from the flex layout.
    input.style.width = "100%";
    const maxWidth = input.clientWidth;
    input.style.width = "10px";
    if (input.value === "" && input.placeholder !== "") {
        input.style.width = "auto";
        return;
    }
    // Span-based measurement keeps text width consistent with the readonly
    // counterpart (see measureTextWidth).
    const textWidth = measureTextWidth(input);
    const width = textWidth + (options?.offset || 0);
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
        borderTopWidth: style.borderTopWidth,
        borderBottomWidth: style.borderBottomWidth,
        padding: style.padding,
    };
    Object.assign(textarea.style, {
        height: "auto",
        borderTopWidth: 0,
        borderBottomWidth: 0,
        paddingTop: 0,
        paddingBottom: 0,
    });
    textarea.style.height = "auto";
    const height = Math.max(minimumHeight, textarea.scrollHeight + heightOffset);
    Object.assign(textarea.style, previousStyle, { height: `${height}px` });
    if (textarea.parentElement) {
        textarea.parentElement.style.height = `${height}px`;
    }
}
