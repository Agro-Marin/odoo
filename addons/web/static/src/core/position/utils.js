// @ts-check
/** @odoo-module native */

import { localization } from "@web/core/l10n/localization";

/**
 * @typedef {"top" | "left" | "bottom" | "right" | "center"} Direction
 * @typedef {"start" | "middle" | "end" | "fit"} Variant
 * @typedef {{[direction: string]: string}} DirectionFlipOrder
 * @typedef {{[variant in Variant]: string}} VariantFlipOrder
 * @typedef {{
 * top: number,
 * left: number,
 * maxHeight?: number;
 * direction: Direction,
 * variant: Variant,
 * variantOffset?: number,
 * [key: string]: any,
 * }} PositioningSolution
 * @typedef ComputePositionOptions
 * @property {HTMLElement | (() => HTMLElement)} [container]
 * @property {number} [margin=0]
 * @property {Direction | `${Direction}-${Variant}`} [position="bottom"]
 * @property {boolean} [flip=true]
 * @property {boolean} [extendedFlipping=false]
 * @property {boolean} [shrink=false]
 */

/** @type {ComputePositionOptions} */
const DEFAULTS = {
    flip: true,
    margin: 0,
    position: "bottom",
};

/** @type {{[d: string]: Direction}} */
const DIRECTIONS = {
    t: "top",
    r: "right",
    b: "bottom",
    l: "left",
    c: "center",
};
/** @type {{[v: string]: Variant}} */
const VARIANTS = { s: "start", m: "middle", e: "end", f: "fit" };
const DIRECTION_FLIP_ORDER = {
    top: "tb",
    right: "rl",
    bottom: "bt",
    left: "lr",
    center: "c",
};
const EXTENDED_DIRECTION_FLIP_ORDER = {
    top: "tbrlc",
    right: "rlbtc",
    bottom: "btrlc",
    left: "lrbtc",
    center: "c",
};
const VARIANT_FLIP_ORDER = { start: "se", middle: "m", end: "es", fit: "f" };

/**
 * @param {HTMLElement} popperEl
 * @param {HTMLElement} targetEl
 * @returns {HTMLIFrameElement?}
 */
function getIFrame(popperEl, targetEl) {
    return (
        [...popperEl.ownerDocument.getElementsByTagName("iframe")].find((iframe) =>
            iframe.contentDocument?.contains(targetEl),
        ) ?? null
    );
}

/**
 * @param {Direction} direction
 * @param {Variant} [variant="middle"]
 * @returns {[Direction, Variant]}
 */
export function reverseForRTL(direction, variant = "middle") {
    if (localization.direction === "rtl") {
        if (["left", "right"].includes(direction)) {
            direction = direction === "left" ? "right" : "left";
        } else if (["start", "end"].includes(variant)) {
            variant = variant === "start" ? "end" : "start";
        }
    }
    return [direction, variant];
}

/**
 * @param {HTMLElement} popper
 * @param {HTMLElement} target
 * @param {ComputePositionOptions} options
 * @returns {PositioningSolution}
 */
function computePosition(
    popper,
    target,
    {
        container,
        extendedFlipping,
        flip,
        margin = DEFAULTS.margin ?? 0,
        position = DEFAULTS.position ?? "bottom",
        shrink,
    },
) {
    const [d, v] = position.split("-");
    const [direction, variant = "middle"] = reverseForRTL(
        /** @type {Direction} */ (d),
        /** @type {Variant} */ (v),
    );
    let directions = [direction[0]];
    if (flip) {
        directions = /** @type {any} */ (
            extendedFlipping
                ? EXTENDED_DIRECTION_FLIP_ORDER[direction]
                : DIRECTION_FLIP_ORDER[direction]
        );
    }
    const variants = VARIANT_FLIP_ORDER[variant];

    if (!container) {
        container = popper.ownerDocument.documentElement;
    } else if (typeof container === "function") {
        container = container();
    }
    const /** @type {HTMLElement} */ cont = /** @type {HTMLElement} */ (container);

    if (variant === "fit") {
        const styleProperty = ["top", "bottom"].includes(direction)
            ? "width"
            : "height";
        popper.style[styleProperty] = getComputedStyle(target)[styleProperty];
    }

    const popperStyle = getComputedStyle(popper);
    const { marginTop, marginLeft, marginRight, marginBottom } = popperStyle;
    const popMargins = {
        top: parseFloat(marginTop),
        left: parseFloat(marginLeft),
        right: parseFloat(marginRight),
        bottom: parseFloat(marginBottom),
    };

    const shouldAccountForIFrame = popper.ownerDocument !== target.ownerDocument;
    const iframe = shouldAccountForIFrame ? getIFrame(popper, target) : null;

    const popBox = popper.getBoundingClientRect();
    const targetBox = target.getBoundingClientRect();
    const contBox = cont.getBoundingClientRect();
    const iframeBox = iframe?.getBoundingClientRect() ?? { top: 0, left: 0 };

    const containerIsHTMLNode = cont === cont.ownerDocument.firstElementChild;
    const containerIsInIframe =
        shouldAccountForIFrame && target.ownerDocument === cont.ownerDocument;

    /** @type {Record<string, number>} */
    const directionsData = {
        t: iframeBox.top + targetBox.top - popMargins.bottom - margin - popBox.height,
        b: iframeBox.top + targetBox.bottom + popMargins.top + margin,
        r: iframeBox.left + targetBox.right + popMargins.left + margin,
        l: iframeBox.left + targetBox.left - popMargins.right - margin - popBox.width,
        c: iframeBox.top + targetBox.top + targetBox.height / 2 - popBox.height / 2,
    };
    /** @type {Record<string, number>} */
    const variantsData = {
        vf: iframeBox.left + targetBox.left,
        vs: iframeBox.left + targetBox.left + popMargins.left,
        vm: iframeBox.left + targetBox.left + targetBox.width / 2 - popBox.width / 2,
        ve: iframeBox.left + targetBox.right - popMargins.right - popBox.width,
        hf: iframeBox.top + targetBox.top,
        hs: iframeBox.top + targetBox.top + popMargins.top,
        hm: iframeBox.top + targetBox.top + targetBox.height / 2 - popBox.height / 2,
        he: iframeBox.top + targetBox.bottom - popMargins.bottom - popBox.height,
    };

    function getPositioningData(/** @type {string} */ d, /** @type {string} */ v) {
        const [direction, variant] = reverseForRTL(DIRECTIONS[d], VARIANTS[v]);
        /** @type {PositioningSolution} */
        const result = { direction, variant, top: 0, left: 0 };
        const vertical = ["t", "b", "c"].includes(d);
        const variantPrefix = vertical ? "v" : "h";
        const directionValue = directionsData[d];
        let variantValue = variantsData[variantPrefix + v];
        const [leftCompensation, topCompensation] = containerIsInIframe
            ? [iframeBox.left, iframeBox.top]
            : [0, 0];

        const [directionSize, variantSize] = vertical
            ? [popBox.height, popBox.width]
            : [popBox.width, popBox.height];
        let [directionMin, directionMax] = vertical
            ? [contBox.top + topCompensation, contBox.bottom + topCompensation]
            : [contBox.left + leftCompensation, contBox.right + leftCompensation];
        let [variantMin, variantMax] = vertical
            ? [contBox.left + leftCompensation, contBox.right + leftCompensation]
            : [contBox.top + topCompensation, contBox.bottom + topCompensation];

        if (containerIsHTMLNode) {
            const [directionScroll, variantScroll] = vertical
                ? [cont.scrollTop, cont.scrollLeft]
                : [cont.scrollLeft, cont.scrollTop];
            directionMin += directionScroll;
            directionMax += directionScroll;
            variantMin += variantScroll;
            variantMax += variantScroll;
        }

        let directionOverflow = 0;
        if (Math.floor(directionValue) < Math.ceil(directionMin)) {
            directionOverflow = Math.floor(directionValue) - Math.ceil(directionMin);
        } else if (
            Math.ceil(directionValue + directionSize) > Math.floor(directionMax)
        ) {
            directionOverflow =
                Math.ceil(directionValue + directionSize) - Math.floor(directionMax);
        }
        let variantOverflow = 0;
        if (Math.floor(variantValue) < Math.ceil(variantMin)) {
            variantOverflow = Math.floor(variantValue) - Math.ceil(variantMin);
        } else if (Math.ceil(variantValue + variantSize) > Math.floor(variantMax)) {
            variantOverflow =
                Math.ceil(variantValue + variantSize) - Math.floor(variantMax);
        }

        let malus = Math.abs(directionOverflow) + (variantOverflow && 1);

        variantValue -= variantOverflow;
        result.variantOffset = -variantOverflow;

        const positioning = vertical
            ? { top: directionValue, left: variantValue }
            : { top: variantValue, left: directionValue };
        result.top = positioning.top - popBox.top;
        result.left = positioning.left - popBox.left;
        if (d === "c") {
            malus = 1.001;
            result.top -= directionOverflow;
        } else if (shrink && malus) {
            const minTop = Math.floor(
                !vertical && v === "s" ? targetBox.top : contBox.top,
            );
            result.top = Math.max(minTop, result.top);

            let height;
            if (vertical) {
                height = Math.abs(
                    targetBox[
                        /** @type {"top" | "bottom" | "left" | "right"} */ (direction)
                    ] - (d === "t" ? directionMin : directionMax),
                );
            } else {
                height = {
                    s: variantMax - targetBox.top,
                    m: variantMax - variantMin,
                    e: targetBox.bottom - variantMin,
                }[/** @type {"s" | "m" | "e"} */ (v)];
            }
            result.maxHeight = Math.floor(height);
        }
        return { result, malus };
    }

    const matches = [];
    for (const d of directions) {
        for (const v of variants) {
            const match = getPositioningData(d, v);
            if (!match.malus) {
                return match.result;
            }
            matches.push(match);
        }
        if (!flip) {
            break;
        }
    }
    return matches.sort((a, b) => a.malus - b.malus)[0].result;
}

/**
 * @param {HTMLElement} popper
 * @param {HTMLElement} target
 * @param {ComputePositionOptions} options
 * @returns {PositioningSolution}
 */
export function reposition(popper, target, options) {
    popper.style.position = "fixed";
    popper.style.top = "0px";
    popper.style.left = "0px";

    const mhState = popperMaxHeightState.get(popper);
    if (mhState && popper.style.maxHeight === mhState.applied) {
        popper.style.maxHeight = mhState.authored;
    }
    const authoredMaxHeight = popper.style.maxHeight;

    const solution = computePosition(popper, target, {
        ...DEFAULTS,
        ...options,
    });

    const { top, left, maxHeight } = solution;
    popper.style.top = `${top}px`;
    popper.style.left = `${left}px`;
    if (maxHeight !== undefined) {
        const existingMaxHeight = getComputedStyle(popper).maxHeight;
        const applied =
            existingMaxHeight !== "none"
                ? `min(${existingMaxHeight}, ${maxHeight}px)`
                : `${maxHeight}px`;
        popper.style.maxHeight = applied;
        popper.style.overflowY = "auto";
        popperMaxHeightState.set(popper, { authored: authoredMaxHeight, applied });
    } else {
        popperMaxHeightState.delete(popper);
    }

    return solution;
}

/**
 * @type {WeakMap<HTMLElement, { authored: string, applied: string }>}
 */
const popperMaxHeightState = new WeakMap();
