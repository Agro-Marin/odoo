/** @odoo-module native */
import { Component, onWillDestroy, onWillUpdateProps, xml } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/translation";
const MINUTE = 60 * 1000;
const HOUR = 60 * MINUTE;
/** Below this distance the label is the fixed "now" / "in a few seconds" text. */
const NOW_THRESHOLD = 45 * 1000;

/**
 * Delay until the rendered label can next differ, given the signed distance to
 * the reference datetime.
 *
 * A past datetime inside the threshold reads "now" for the whole window, so it
 * only needs waking at the threshold. Scheduling on the raw distance instead
 * (as this did) re-rendered at 5ms, 10ms, 20ms, ... for a just-posted message —
 * around fourteen renders in the first 45 seconds, all producing "now".
 *
 * A future datetime keeps counting down, so it needs both the coarse cadence
 * and the moment it becomes present, whichever lands first: rounding that up to
 * a full cadence tick would show a stale "in a few seconds" past the crossing.
 *
 * @param {number} delta now - datetime, in ms (negative for a future datetime)
 * @returns {number} ms until the next possible label change
 */
export function computeUpdateDelay(delta) {
    const absDelta = Math.abs(delta);
    const cadence = absDelta < HOUR ? MINUTE : HOUR;
    let delay;
    if (delta < 0) {
        delay = Math.min(absDelta, cadence);
    } else if (absDelta < NOW_THRESHOLD) {
        delay = NOW_THRESHOLD - absDelta;
    } else {
        delay = cadence;
    }
    return Math.max(delay, 1);
}

export class RelativeTime extends Component {
    static props = ["datetime"];
    static template = xml`<t t-esc="relativeTime"/>`;

    setup() {
        super.setup();
        this.timeout = null;
        this.computeRelativeTime(this.props.datetime);
        onWillDestroy(() => browser.clearTimeout(this.timeout));
        onWillUpdateProps((nextProps) => {
            browser.clearTimeout(this.timeout);
            this.computeRelativeTime(nextProps.datetime);
        });
    }

    computeRelativeTime(datetime) {
        if (!datetime) {
            this.relativeTime = "";
            return;
        }
        const delta = Date.now() - datetime.ts;
        if (Math.abs(delta) < NOW_THRESHOLD) {
            this.relativeTime = delta < 0 ? _t("in a few seconds") : _t("now");
        } else {
            this.relativeTime = datetime.toRelative();
        }
        this.timeout = browser.setTimeout(() => {
            this.computeRelativeTime(this.props.datetime);
            this.render();
        }, computeUpdateDelay(delta));
    }
}
