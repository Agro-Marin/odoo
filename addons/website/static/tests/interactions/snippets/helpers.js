import { advanceTime, animationFrame, scroll } from "@odoo/hoot-dom";
import { defineStyle } from "@web/../tests/web_test_helpers";

export async function endTransition() {
    await animationFrame();
    await advanceTime(500);
}

/**
 * @param {any} core
 * @param {any} wrapwrap
 */
export async function setupTest(core, wrapwrap) {
    wrapwrap.style.height = "800px";
    wrapwrap.style.width = "100%";
    wrapwrap.style.overflow = "scroll";
    core.interactions[0].interaction.scrollingElement = wrapwrap;
    defineStyle(`.hidden { display: none !important; }`);
    defineStyle(`.h20 { height: 20px; }`);
    await endTransition();
}

/**
 * @param {Parameters<scroll>[0]} wrapwrapEl
 * @param {Parameters<scroll>[1]} target
 */
export async function simpleScroll(wrapwrapEl, target) {
    await scroll(wrapwrapEl, target, { scrollable: false });
    await endTransition();
}

/**
 * @param {Parameters<scroll>[0]} wrapwrapEl
 * @param {number} target
 * @param {number} source
 */
export async function doubleScroll(wrapwrapEl, target, source) {
    await scroll(wrapwrapEl, { y: source + (target > source ? 1 : -1) });
    await scroll(wrapwrapEl, { y: target });
    await endTransition();
}
