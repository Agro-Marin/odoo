// @ts-check
/** @odoo-module native */

/** @module @web/webclient/swipe - Shared horizontal swipe-to-dismiss gesture tracking */

/**
 * Minimum horizontal travel, in CSS pixels, before a touch counts as a
 * dismissing swipe rather than a stray drag.
 */
export const SWIPE_ACTIVATION_THRESHOLD = 100;

/** Swipe travelling left (towards decreasing x) dismisses. */
export const SWIPE_LEFT = -1;
/** Swipe travelling right (towards increasing x) dismisses. */
export const SWIPE_RIGHT = 1;

/**
 * Tracks one horizontal swipe gesture in a given dismissing direction.
 *
 * @example
 *   this.swipe = new SwipeTracker(SWIPE_LEFT);
 *   _onSwipeStart(ev) { this.swipe.start(ev); }
 *   _onSwipeEnd(ev) { if (this.swipe.end(ev)) { this.close(); } }
 */
export class SwipeTracker {
    /** @param {-1 | 1} direction one of {@link SWIPE_LEFT} / {@link SWIPE_RIGHT} */
    constructor(direction) {
        this.direction = direction;
        /** @type {number | null} */
        this.startX = null;
    }

    /** @param {TouchEvent} ev */
    start(ev) {
        this.startX = ev.changedTouches[0].clientX;
    }

    /**
     * Close the gesture and report whether it qualifies.
     *
     * The pending check is `=== null`, not falsy: `clientX === 0` is a real
     * coordinate — a touch begun at the very left edge of the screen, which is
     * exactly where an edge swipe starts.
     *
     * @param {TouchEvent} ev
     * @returns {boolean} true if the swipe travelled far enough to dismiss
     */
    end(ev) {
        if (this.startX === null) {
            return false;
        }
        const travel = (ev.changedTouches[0].clientX - this.startX) * this.direction;
        this.startX = null;
        return travel >= SWIPE_ACTIVATION_THRESHOLD;
    }
}
