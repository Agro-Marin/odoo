// @ts-check
/** @odoo-module native */

/** @module @web/libs/popper_compat - Popper v2 `createPopper` over the in-house position engine */

import { localization } from "@web/core/l10n/localization";
import { reposition, reverseForRTL } from "@web/core/position/utils";

/**
 * The slice of Popper v2's API that Bootstrap 5.3 actually uses.
 *
 * Bootstrap is the only consumer of Popper in this codebase — nothing else
 * imports it — and it touches exactly one entry point, `createPopper`, at two
 * call sites (`Dropdown._createPopper`, `Tooltip._createPopper`), then calls
 * only `update()` and `destroy()` on the result. That narrow surface is what
 * makes replacing a 60 kB dependency with this module worthwhile.
 *
 * Positioning is delegated to `@web/core/position/utils`, which already
 * implements flipping, RTL, container clamping and shrink-to-fit for the
 * webclient's own overlays. Reusing it means one positioning engine instead
 * of two.
 *
 * Why not CSS anchor positioning, which is Baseline as of 2026: the browser
 * picks the fallback internally and exposes no way to read back which one it
 * used. Bootstrap needs the resolved placement — it writes it to
 * `data-popper-placement`, and its arrow/caret CSS keys off that attribute —
 * so a pure-CSS implementation could not tell Bootstrap where the element
 * actually landed. `reposition()` returns the resolved direction and variant,
 * which is exactly the missing piece.
 *
 * Reached two ways, because Bootstrap is loaded two ways. Bundled code gets
 * this source inlined by esbuild (the `@popperjs/core` alias in
 * `odoo/tools/assets/esbuild.py`). Pages outside the asset pipeline — the IoT
 * box homepage, the database manager, the error page — load
 * `bootstrap.esm.js` straight into the browser and resolve the same specifier
 * through an import map; having no bundler, they cannot follow the
 * `@web/...` imports above, so they get the self-contained build at
 * `static/lib/popper_compat/`. That build is generated from this file, and
 * `check_vendored_libs.py --drift` fails if it goes stale.
 */

/** Popper placements that mean "decide for me". */
const AUTO_PLACEMENTS = new Set(["auto", "auto-start", "auto-end"]);

/**
 * Guarantee the position engine can read a text direction.
 *
 * The engine mirrors placements for RTL by reading `localization.direction`,
 * which the localization *service* populates. Bootstrap also runs on pages
 * that never boot that service — the IoT box homepage, the database manager,
 * the error page — where the `localization` proxy throws on any unset key by
 * design, to catch a webclient module forgetting its dependency. Positioning
 * a dropdown there must not be fatal, so fall back to what the document
 * itself declares, which is the real source of truth for RTL rendering.
 *
 * Only fills a gap: the service does `Object.assign(localization, ...)`, so
 * inside the webclient this either finds the value already set or is
 * overwritten with the authoritative one.
 */
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
 * Convert a placement between physical and logical space.
 *
 * Popper treats placements as purely physical, and Bootstrap relies on that:
 * it resolves RTL itself, picking `top-end` over `top-start` and `left` over
 * `right` before it ever calls `createPopper`. The in-house engine instead
 * speaks logical placements — it mirrors on the way in *and* mirrors again
 * when reporting the result — so handing it Bootstrap's physical placement
 * unchanged would mirror it a second time and send every RTL dropdown to the
 * wrong side.
 *
 * `reverseForRTL` is its own inverse and a no-op in LTR, so the same call
 * serves both conversions: physical in, logical out.
 *
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
 * Translate a Popper placement into the position string the in-house engine
 * takes.
 *
 * Popper writes the cross-axis alignment as an optional `-start` / `-end`
 * suffix and leaves centred implicit; the engine names that centre case
 * `middle` but also defaults to it, so a bare direction passes through.
 *
 * @param {string} placement e.g. `"bottom"`, `"left-end"`, `"auto"`
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
 * Turn a resolved engine solution back into a Popper placement string.
 *
 * @param {{ direction: string, variant: string }} solution
 * @returns {string}
 */
function toPopperPlacement({ direction, variant }) {
    return variant === "middle" || variant === "fit"
        ? direction
        : `${direction}-${variant}`;
}

/**
 * Read Popper's `offset` modifier as the engine's `margin`.
 *
 * Popper takes `[skidding, distance]` — cross-axis then main-axis — and also
 * accepts a function returning that pair. Only `distance` maps onto the
 * engine, which has no cross-axis nudge; `skidding` is applied by hand after
 * positioning (see {@link applySkidding}).
 *
 * @param {any} modifier the `offset` modifier, if present
 * @param {string} placement the resolved placement, passed to the fn form
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
 * Shift the popper along its cross axis by Popper's `skidding` offset.
 *
 * @param {HTMLElement} popper
 * @param {string} direction the resolved main-axis direction
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
 * Centre Bootstrap's arrow on the reference along the popper's cross axis.
 *
 * Bootstrap's stylesheet places the arrow on the correct edge from
 * `data-popper-placement`; what it cannot know is how far along that edge the
 * reference sits once the popper has been clamped to its container. Popper
 * supplied that as an inline offset on the arrow element, so this does too.
 *
 * @param {HTMLElement | null} arrow
 * @param {HTMLElement} popper
 * @param {DOMRect} referenceRect
 * @param {string} direction the resolved main-axis direction
 */
function positionArrow(arrow, popper, referenceRect, direction) {
    if (!arrow) {
        return;
    }
    const popperRect = popper.getBoundingClientRect();
    const horizontal = direction === "top" || direction === "bottom";
    // Reset the axis we do not drive, so a re-position after a flip does not
    // keep the offset it wrote for the previous edge.
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
 * Resolve the `preventOverflow` boundary into a container element.
 *
 * Bootstrap's default is the string `"clippingParents"`, and it also accepts
 * an element. Only the element form maps onto the engine; anything else falls
 * through to the engine's own default container.
 *
 * @param {any} modifier the `preventOverflow` modifier, if present
 * @returns {HTMLElement | undefined}
 */
function readBoundary(modifier) {
    const boundary = modifier?.options?.boundary;
    return boundary instanceof HTMLElement ? boundary : undefined;
}

/**
 * Popper v2's `createPopper`, reimplemented over the in-house position engine.
 *
 * Only the behaviour Bootstrap depends on is implemented — see the module
 * comment. Unknown modifiers are ignored rather than rejected, matching
 * Popper's own tolerance for extra entries.
 *
 * @param {HTMLElement | { getBoundingClientRect: () => DOMRect }} reference
 * @param {HTMLElement} popper
 * @param {any} [config] Popper options (`placement`, `modifiers`)
 * @returns {{ update: () => void, destroy: () => void, state: any }}
 */
export function createPopper(reference, popper, config = {}) {
    const modifiers = new Map(
        (config.modifiers ?? []).filter((m) => m?.name).map((m) => [m.name, m]),
    );

    // Bootstrap disables `applyStyles` to mean "leave this element where the
    // stylesheet put it" (a static dropdown, or one inside a navbar).
    const inert = modifiers.get("applyStyles")?.enabled === false;

    const arrowSelector = modifiers.get("arrow")?.options?.element;
    const preSetPlacement = modifiers.get("preSetPlacement");
    const flipEnabled = modifiers.get("flip")?.enabled !== false;

    const state = { placement: config.placement ?? "bottom", elements: { reference, popper } };

    function update() {
        if (inert || !popper.isConnected) {
            return;
        }
        ensureDirection();
        const { position, extendedFlipping } = toEnginePosition(config.placement);
        const { margin, skidding } = readOffset(modifiers.get("offset"), state.placement);

        const solution = reposition(popper, /** @type {any} */ (reference), {
            position: mirror(position),
            extendedFlipping,
            flip: flipEnabled,
            margin,
            container: readBoundary(modifiers.get("preventOverflow")),
        });

        state.placement = mirror(toPopperPlacement(solution));
        // Bootstrap reads this attribute from its own `preSetPlacement`
        // modifier to size the arrow before the main phase, and its
        // stylesheet selects on it. Write it before anything measures.
        popper.setAttribute("data-popper-placement", state.placement);
        preSetPlacement?.fn?.({ state });

        applySkidding(popper, solution.direction, skidding);
        if (arrowSelector) {
            const arrow =
                typeof arrowSelector === "string"
                    ? popper.querySelector(arrowSelector)
                    : arrowSelector;
            positionArrow(arrow, popper, reference.getBoundingClientRect(), solution.direction);
        }
    }

    // Popper tracks ancestor scroll and viewport resize; `capture` catches
    // scrolls on intermediate containers, which do not bubble.
    const onViewportChange = () => update();
    if (!inert) {
        window.addEventListener("scroll", onViewportChange, { capture: true, passive: true });
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
