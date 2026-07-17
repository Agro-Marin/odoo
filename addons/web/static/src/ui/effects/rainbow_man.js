// @ts-check
/** @odoo-module native */

/** @module @web/ui/effects/rainbow_man - Animated rainbow celebration overlay with configurable message and fadeout */

import { Component, useEffect, useExternalListener, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
/**
 * @typedef Common
 * @property {string} [fadeout='medium'] Delay before disappearing: 'fast' is
 *  quick, 'medium'/'slow' wait longer (for longer messages), 'no' keeps it
 *  until the user clicks outside.
 * @property {string} [imgUrl] URL of the image to be displayed
 *
 * @typedef Simple
 * @property {string} message Message to be displayed on rainbowman card
 *
 * @typedef Custom
 * @property {import("@odoo/owl").ComponentConstructor} Component
 * @property {any} [props]
 *
 * @typedef {Common & (Simple | Custom)} RainbowManProps
 */

/**
 * Displays a rewarding message (e.g. large deal won, inbox cleared) as a
 * picture with a rainbow animation. Prefer the effect service over
 * importing this file directly.
 */
export class RainbowMan extends Component {
    static template = "web.RainbowMan";
    static rainbowFadeouts = {
        slow: 4500,
        medium: 3500,
        fast: 2000,
        no: false,
    };
    static props = {
        fadeout: String,
        close: Function,
        message: String,
        imgUrl: String,
        Component: { type: Function, optional: true },
        props: { type: Object, optional: true },
    };

    setup() {
        useExternalListener(document.body, "click", this.closeRainbowMan);
        this.state = useState({ isFading: false });
        // Unknown fadeout keys (e.g. a server-supplied typo) would yield
        // ``undefined`` and disable auto-close, leaving the rainbowman stuck
        // forever. Fall back to "medium". ``??`` (not ``||``) preserves the
        // intentional ``no: false`` value that keeps it up until a click.
        this.delay =
            /** @type {Record<string, number | false>} */ (RainbowMan.rainbowFadeouts)[
                this.props.fadeout
            ] ?? RainbowMan.rainbowFadeouts.medium;
        if (this.delay) {
            useEffect(
                () => {
                    const timeout = browser.setTimeout(() => {
                        this.state.isFading = true;
                    }, /** @type {number} */ (this.delay));
                    return () => browser.clearTimeout(timeout);
                },
                () => [],
            );
        }
    }

    /** @param {AnimationEvent} ev */
    onAnimationEnd(ev) {
        if (this.delay && ev.animationName === "reward-fading-reverse") {
            ev.stopPropagation();
            this.closeRainbowMan();
        }
    }

    closeRainbowMan() {
        this.props.close();
    }
}
