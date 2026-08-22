// @ts-check
/** @odoo-module native */

import { localization } from "@web/core/l10n/localization";
import { reposition, reverseForRTL } from "@web/core/position/utils";

const AUTO_PLACEMENTS = new Set(["auto", "auto-start", "auto-end"]);

function ensureDirection() {
    if (!("direction" in localization)) {
        localization.direction =
            document.documentElement.getAttribute("dir") === "rtl" ||
            getComputedStyle(document.documentElement).direction === "rtl"
                ? "rtl"
                : "ltr";
    }
}

/**
 * @param {string} placement
 * @returns {string}
 */
function mirror(placement) {
    const [d, v = "middle"] = placement.split("-");
    const [direction, variant] = reverseForRTL(
        /** @type {any} */ (d),
        /** @type {any} */ (v),
    );
    return variant === "middle" ? direction : `${direction}-${variant}`;
}

/**
 * @param {string} placement
 * @returns {{ position: string, extendedFlipping: boolean }}
 */
function toEnginePosition(placement) {
    if (!placement || AUTO_PLACEMENTS.has(placement)) {
        const variant = placement?.split("-")[1];
        return {
            position: variant ? `bottom-${variant}` : "bottom",
            extendedFlipping: true,
        };
    }
    return { position: placement, extendedFlipping: false };
}

/**
 * @param {{ direction: string, variant: string }} solution
 * @returns {string}
 */
function toPopperPlacement({ direction, variant }) {
    return variant === "middle" || variant === "fit"
        ? direction
        : `${direction}-${variant}`;
}

/**
 * @param {any} modifier
 * @param {string} placement
 * @returns {{ margin: number, skidding: number }}
 */
function readOffset(modifier, placement) {
    let offset = modifier?.options?.offset ?? 0;
    if (typeof offset === "function") {
        offset = offset({ placement }) ?? 0;
    }
    const [skidding = 0, distance = 0] = Array.isArray(offset) ? offset : [0, offset];
    return { margin: distance, skidding };
}

/**
 * @param {HTMLElement} popper
 * @param {string} direction
 * @param {number} skidding
 */
function applySkidding(popper, direction, skidding) {
    if (!skidding) {
        return;
    }
    const horizontal = direction === "top" || direction === "bottom";
    const prop = horizontal ? "left" : "top";
    popper.style[prop] = `${parseFloat(popper.style[prop] || "0") + skidding}px`;
}

/**
 * @param {HTMLElement | null} arrow
 * @param {HTMLElement} popper
 * @param {DOMRect} referenceRect
 * @param {string} direction
 */
function positionArrow(arrow, popper, referenceRect, direction) {
    if (!arrow) {
        return;
    }
    const popperRect = popper.getBoundingClientRect();
    const horizontal = direction === "top" || direction === "bottom";
    arrow.style.top = "";
    arrow.style.left = "";
    if (horizontal) {
        const centre = referenceRect.left + referenceRect.width / 2 - popperRect.left;
        const bound = popperRect.width - arrow.offsetWidth;
        const value = Math.max(0, Math.min(centre - arrow.offsetWidth / 2, bound));
        arrow.style.left = `${value}px`;
    } else {
        const centre = referenceRect.top + referenceRect.height / 2 - popperRect.top;
        const bound = popperRect.height - arrow.offsetHeight;
        const value = Math.max(0, Math.min(centre - arrow.offsetHeight / 2, bound));
        arrow.style.top = `${value}px`;
    }
}

/**
 * @param {any} modifier
 * @returns {HTMLElement | undefined}
 */
function readBoundary(modifier) {
    const boundary = modifier?.options?.boundary;
    return boundary instanceof HTMLElement ? boundary : undefined;
}

/**
 * @param {HTMLElement | { getBoundingClientRect: () => DOMRect }} reference
 * @param {HTMLElement} popper
 * @param {any} [config]
 * @returns {{ update: () => void, destroy: () => void, state: any }}
 */
export function createPopper(reference, popper, config = {}) {
    const modifiers = new Map(
        (config.modifiers ?? []).filter((m) => m?.name).map((m) => [m.name, m]),
    );

    const inert = modifiers.get("applyStyles")?.enabled === false;

    const arrowSelector = modifiers.get("arrow")?.options?.element;
    const preSetPlacement = modifiers.get("preSetPlacement");
    const flipEnabled = modifiers.get("flip")?.enabled !== false;

    const state = {
        placement: config.placement ?? "bottom",
        elements: { reference, popper },
    };

    function update() {
        if (inert || !popper.isConnected) {
            return;
        }
        ensureDirection();
        const { position, extendedFlipping } = toEnginePosition(config.placement);
        const { margin, skidding } = readOffset(
            modifiers.get("offset"),
            state.placement,
        );

        const solution = reposition(popper, /** @type {any} */ (reference), {
            position: mirror(position),
            extendedFlipping,
            flip: flipEnabled,
            margin,
            container: readBoundary(modifiers.get("preventOverflow")),
        });

        state.placement = mirror(toPopperPlacement(solution));
        popper.setAttribute("data-popper-placement", state.placement);
        preSetPlacement?.fn?.({ state });

        applySkidding(popper, solution.direction, skidding);
        if (arrowSelector) {
            const arrow =
                typeof arrowSelector === "string"
                    ? popper.querySelector(arrowSelector)
                    : arrowSelector;
            positionArrow(
                arrow,
                popper,
                reference.getBoundingClientRect(),
                solution.direction,
            );
        }
    }

    const onViewportChange = () => update();
    if (!inert) {
        window.addEventListener("scroll", onViewportChange, {
            capture: true,
            passive: true,
        });
        window.addEventListener("resize", onViewportChange, { passive: true });
    }

    update();

    return {
        state,
        update,
        destroy() {
            window.removeEventListener("scroll", onViewportChange, { capture: true });
            window.removeEventListener("resize", onViewportChange);
            popper.removeAttribute("data-popper-placement");
        },
    };
}
