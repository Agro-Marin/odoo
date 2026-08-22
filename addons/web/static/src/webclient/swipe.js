// @ts-check
/** @odoo-module native */

export const SWIPE_ACTIVATION_THRESHOLD = 100;

export const SWIPE_LEFT = -1;
export const SWIPE_RIGHT = 1;

export class SwipeTracker {
    /** @param {-1 | 1} direction */
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
     * @param {TouchEvent} ev
     * @returns {boolean}
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
