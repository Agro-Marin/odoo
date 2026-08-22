// @ts-check
/** @odoo-module native */

import { Component, useEffect, useExternalListener, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
/**
 * @typedef Common
 * @property {string} [fadeout='medium']
 * @property {string} [imgUrl]
 * @typedef Simple
 * @property {string} message
 * @typedef Custom
 * @property {import("@odoo/owl").ComponentConstructor} Component
 * @property {any} [props]
 * @typedef {Common & (Simple | Custom)} RainbowManProps
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

    /** @type {{ isFading: boolean }} */
    state;

    setup() {
        useExternalListener(document.body, "click", this.onBodyClick);
        this.state = useState({ isFading: false });
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

    /**
     * @param {MouseEvent} ev
     */
    onBodyClick(ev) {
        if (
            this.props.Component &&
            /** @type {Element} */ (ev.target)?.closest?.(".o_reward_msg_content")
        ) {
            return;
        }
        this.closeRainbowMan();
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
