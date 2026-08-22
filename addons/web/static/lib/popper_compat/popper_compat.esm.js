/**
 * Self-contained build of @web/libs/popper_compat, for pages that resolve
 * `@popperjs/core` through an import map instead of a bundler.
 *
 * GENERATED -- do not edit. Rebuild with:
 *     addons/web/static/lib/popper_compat/build.sh
 * Its freshness is enforced by:
 *     tooling/vendored/check_vendored_libs.py --drift
 *
 * @license LGPL-3 (this is first-party Odoo code, not a vendored library)
 */
// addons/web/static/src/core/l10n/localization.js
var ALLOWED_PROTOCOL_KEYS = /* @__PURE__ */ new Set([
  "then",
  "toJSON",
  "constructor",
  "inspect",
  "destroy"
]);
var localization = new Proxy(
  /** @type {any} */
  {},
  {
    get: (target, p) => {
      if (typeof p === "symbol" || p in target || ALLOWED_PROTOCOL_KEYS.has(p)) {
        return Reflect.get(target, p);
      }
      throw new Error(
        `could not access localization parameter "${String(p)}": parameters are not ready yet. Maybe add 'localization' to your dependencies?`
      );
    }
  }
);

// addons/web/static/src/core/position/utils.js
var DEFAULTS = {
  flip: true,
  margin: 0,
  position: "bottom"
};
var DIRECTIONS = {
  t: "top",
  r: "right",
  b: "bottom",
  l: "left",
  c: "center"
};
var VARIANTS = { s: "start", m: "middle", e: "end", f: "fit" };
var DIRECTION_FLIP_ORDER = {
  top: "tb",
  right: "rl",
  bottom: "bt",
  left: "lr",
  center: "c"
};
var EXTENDED_DIRECTION_FLIP_ORDER = {
  top: "tbrlc",
  right: "rlbtc",
  bottom: "btrlc",
  left: "lrbtc",
  center: "c"
};
var VARIANT_FLIP_ORDER = { start: "se", middle: "m", end: "es", fit: "f" };
function getIFrame(popperEl, targetEl) {
  return [...popperEl.ownerDocument.getElementsByTagName("iframe")].find(
    (iframe) => iframe.contentDocument?.contains(targetEl)
  ) ?? null;
}
function reverseForRTL(direction, variant = "middle") {
  if (localization.direction === "rtl") {
    if (["left", "right"].includes(direction)) {
      direction = direction === "left" ? "right" : "left";
    } else if (["start", "end"].includes(variant)) {
      variant = variant === "start" ? "end" : "start";
    }
  }
  return [direction, variant];
}
function computePosition(popper, target, {
  container,
  extendedFlipping,
  flip,
  margin = DEFAULTS.margin ?? 0,
  position = DEFAULTS.position ?? "bottom",
  shrink
}) {
  const [d, v] = position.split("-");
  const [direction, variant = "middle"] = reverseForRTL(
    /** @type {Direction} */
    d,
    /** @type {Variant} */
    v
  );
  let directions = [direction[0]];
  if (flip) {
    directions = /** @type {any} */
    extendedFlipping ? EXTENDED_DIRECTION_FLIP_ORDER[direction] : DIRECTION_FLIP_ORDER[direction];
  }
  const variants = VARIANT_FLIP_ORDER[variant];
  if (!container) {
    container = popper.ownerDocument.documentElement;
  } else if (typeof container === "function") {
    container = container();
  }
  const cont = (
    /** @type {HTMLElement} */
    container
  );
  if (variant === "fit") {
    const styleProperty = ["top", "bottom"].includes(direction) ? "width" : "height";
    popper.style[styleProperty] = getComputedStyle(target)[styleProperty];
  }
  const popperStyle = getComputedStyle(popper);
  const { marginTop, marginLeft, marginRight, marginBottom } = popperStyle;
  const popMargins = {
    top: parseFloat(marginTop),
    left: parseFloat(marginLeft),
    right: parseFloat(marginRight),
    bottom: parseFloat(marginBottom)
  };
  const shouldAccountForIFrame = popper.ownerDocument !== target.ownerDocument;
  const iframe = shouldAccountForIFrame ? getIFrame(popper, target) : null;
  const popBox = popper.getBoundingClientRect();
  const targetBox = target.getBoundingClientRect();
  const contBox = cont.getBoundingClientRect();
  const iframeBox = iframe?.getBoundingClientRect() ?? { top: 0, left: 0 };
  const containerIsHTMLNode = cont === cont.ownerDocument.firstElementChild;
  const containerIsInIframe = shouldAccountForIFrame && target.ownerDocument === cont.ownerDocument;
  const directionsData = {
    t: iframeBox.top + targetBox.top - popMargins.bottom - margin - popBox.height,
    b: iframeBox.top + targetBox.bottom + popMargins.top + margin,
    r: iframeBox.left + targetBox.right + popMargins.left + margin,
    l: iframeBox.left + targetBox.left - popMargins.right - margin - popBox.width,
    c: iframeBox.top + targetBox.top + targetBox.height / 2 - popBox.height / 2
  };
  const variantsData = {
    vf: iframeBox.left + targetBox.left,
    vs: iframeBox.left + targetBox.left + popMargins.left,
    vm: iframeBox.left + targetBox.left + targetBox.width / 2 - popBox.width / 2,
    ve: iframeBox.left + targetBox.right - popMargins.right - popBox.width,
    hf: iframeBox.top + targetBox.top,
    hs: iframeBox.top + targetBox.top + popMargins.top,
    hm: iframeBox.top + targetBox.top + targetBox.height / 2 - popBox.height / 2,
    he: iframeBox.top + targetBox.bottom - popMargins.bottom - popBox.height
  };
  function getPositioningData(d2, v2) {
    const [direction2, variant2] = reverseForRTL(DIRECTIONS[d2], VARIANTS[v2]);
    const result = { direction: direction2, variant: variant2, top: 0, left: 0 };
    const vertical = ["t", "b", "c"].includes(d2);
    const variantPrefix = vertical ? "v" : "h";
    const directionValue = directionsData[d2];
    let variantValue = variantsData[variantPrefix + v2];
    const [leftCompensation, topCompensation] = containerIsInIframe ? [iframeBox.left, iframeBox.top] : [0, 0];
    const [directionSize, variantSize] = vertical ? [popBox.height, popBox.width] : [popBox.width, popBox.height];
    let [directionMin, directionMax] = vertical ? [contBox.top + topCompensation, contBox.bottom + topCompensation] : [contBox.left + leftCompensation, contBox.right + leftCompensation];
    let [variantMin, variantMax] = vertical ? [contBox.left + leftCompensation, contBox.right + leftCompensation] : [contBox.top + topCompensation, contBox.bottom + topCompensation];
    if (containerIsHTMLNode) {
      const [directionScroll, variantScroll] = vertical ? [cont.scrollTop, cont.scrollLeft] : [cont.scrollLeft, cont.scrollTop];
      directionMin += directionScroll;
      directionMax += directionScroll;
      variantMin += variantScroll;
      variantMax += variantScroll;
    }
    let directionOverflow = 0;
    if (Math.floor(directionValue) < Math.ceil(directionMin)) {
      directionOverflow = Math.floor(directionValue) - Math.ceil(directionMin);
    } else if (Math.ceil(directionValue + directionSize) > Math.floor(directionMax)) {
      directionOverflow = Math.ceil(directionValue + directionSize) - Math.floor(directionMax);
    }
    let variantOverflow = 0;
    if (Math.floor(variantValue) < Math.ceil(variantMin)) {
      variantOverflow = Math.floor(variantValue) - Math.ceil(variantMin);
    } else if (Math.ceil(variantValue + variantSize) > Math.floor(variantMax)) {
      variantOverflow = Math.ceil(variantValue + variantSize) - Math.floor(variantMax);
    }
    let malus = Math.abs(directionOverflow) + (variantOverflow && 1);
    variantValue -= variantOverflow;
    result.variantOffset = -variantOverflow;
    const positioning = vertical ? { top: directionValue, left: variantValue } : { top: variantValue, left: directionValue };
    result.top = positioning.top - popBox.top;
    result.left = positioning.left - popBox.left;
    if (d2 === "c") {
      malus = 1.001;
      result.top -= directionOverflow;
    } else if (shrink && malus) {
      const minTop = Math.floor(
        !vertical && v2 === "s" ? targetBox.top : contBox.top
      );
      result.top = Math.max(minTop, result.top);
      let height;
      if (vertical) {
        height = Math.abs(
          targetBox[
            /** @type {"top" | "bottom" | "left" | "right"} */
            direction2
          ] - (d2 === "t" ? directionMin : directionMax)
        );
      } else {
        height = {
          s: variantMax - targetBox.top,
          m: variantMax - variantMin,
          e: targetBox.bottom - variantMin
        }[
          /** @type {"s" | "m" | "e"} */
          v2
        ];
      }
      result.maxHeight = Math.floor(height);
    }
    return { result, malus };
  }
  const matches = [];
  for (const d2 of directions) {
    for (const v2 of variants) {
      const match = getPositioningData(d2, v2);
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
function reposition(popper, target, options) {
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
    ...options
  });
  const { top, left, maxHeight } = solution;
  popper.style.top = `${top}px`;
  popper.style.left = `${left}px`;
  if (maxHeight !== void 0) {
    const existingMaxHeight = getComputedStyle(popper).maxHeight;
    const applied = existingMaxHeight !== "none" ? `min(${existingMaxHeight}, ${maxHeight}px)` : `${maxHeight}px`;
    popper.style.maxHeight = applied;
    popper.style.overflowY = "auto";
    popperMaxHeightState.set(popper, { authored: authoredMaxHeight, applied });
  } else {
    popperMaxHeightState.delete(popper);
  }
  return solution;
}
var popperMaxHeightState = /* @__PURE__ */ new WeakMap();

// addons/web/static/src/libs/popper_compat.js
var AUTO_PLACEMENTS = /* @__PURE__ */ new Set(["auto", "auto-start", "auto-end"]);
function ensureDirection() {
  if (!("direction" in localization)) {
    localization.direction = document.documentElement.getAttribute("dir") === "rtl" || getComputedStyle(document.documentElement).direction === "rtl" ? "rtl" : "ltr";
  }
}
function mirror(placement) {
  const [d, v = "middle"] = placement.split("-");
  const [direction, variant] = reverseForRTL(
    /** @type {any} */
    d,
    /** @type {any} */
    v
  );
  return variant === "middle" ? direction : `${direction}-${variant}`;
}
function toEnginePosition(placement) {
  if (!placement || AUTO_PLACEMENTS.has(placement)) {
    const variant = placement?.split("-")[1];
    return {
      position: variant ? `bottom-${variant}` : "bottom",
      extendedFlipping: true
    };
  }
  return { position: placement, extendedFlipping: false };
}
function toPopperPlacement({ direction, variant }) {
  return variant === "middle" || variant === "fit" ? direction : `${direction}-${variant}`;
}
function readOffset(modifier, placement) {
  let offset = modifier?.options?.offset ?? 0;
  if (typeof offset === "function") {
    offset = offset({ placement }) ?? 0;
  }
  const [skidding = 0, distance = 0] = Array.isArray(offset) ? offset : [0, offset];
  return { margin: distance, skidding };
}
function applySkidding(popper, direction, skidding) {
  if (!skidding) {
    return;
  }
  const horizontal = direction === "top" || direction === "bottom";
  const prop = horizontal ? "left" : "top";
  popper.style[prop] = `${parseFloat(popper.style[prop] || "0") + skidding}px`;
}
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
function readBoundary(modifier) {
  const boundary = modifier?.options?.boundary;
  return boundary instanceof HTMLElement ? boundary : void 0;
}
function createPopper(reference, popper, config = {}) {
  const modifiers = new Map(
    (config.modifiers ?? []).filter((m) => m?.name).map((m) => [m.name, m])
  );
  const inert = modifiers.get("applyStyles")?.enabled === false;
  const arrowSelector = modifiers.get("arrow")?.options?.element;
  const preSetPlacement = modifiers.get("preSetPlacement");
  const flipEnabled = modifiers.get("flip")?.enabled !== false;
  const state = {
    placement: config.placement ?? "bottom",
    elements: { reference, popper }
  };
  function update() {
    if (inert || !popper.isConnected) {
      return;
    }
    ensureDirection();
    const { position, extendedFlipping } = toEnginePosition(config.placement);
    const { margin, skidding } = readOffset(
      modifiers.get("offset"),
      state.placement
    );
    const solution = reposition(
      popper,
      /** @type {any} */
      reference,
      {
        position: mirror(position),
        extendedFlipping,
        flip: flipEnabled,
        margin,
        container: readBoundary(modifiers.get("preventOverflow"))
      }
    );
    state.placement = mirror(toPopperPlacement(solution));
    popper.setAttribute("data-popper-placement", state.placement);
    preSetPlacement?.fn?.({ state });
    applySkidding(popper, solution.direction, skidding);
    if (arrowSelector) {
      const arrow = typeof arrowSelector === "string" ? popper.querySelector(arrowSelector) : arrowSelector;
      positionArrow(
        arrow,
        popper,
        reference.getBoundingClientRect(),
        solution.direction
      );
    }
  }
  const onViewportChange = () => update();
  if (!inert) {
    window.addEventListener("scroll", onViewportChange, {
      capture: true,
      passive: true
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
    }
  };
}
export {
  createPopper
};
