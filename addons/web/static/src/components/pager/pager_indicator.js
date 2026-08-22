// @ts-check
/** @odoo-module native */

import { Component, onWillUnmount, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { PagerEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { Transition } from "@web/core/transition";
import { useBus } from "@web/core/utils/hooks";

export class PagerIndicator extends Component {
    static template = "web.PagerIndicator";
    static components = { Transition };
    static props = {};

    /** @type {number | undefined} */
    startShowTimer;
    /** @type {{ show: boolean; value: string; total: number }} */
    state;

    setup() {
        this.state = useState({
            show: false,
            value: "-",
            total: 0,
        });
        useBus(this.env.bus, PagerEvent.UPDATED, this.pagerUpdate);
        onWillUnmount(() => browser.clearTimeout(this.startShowTimer));
    }

    /** @param {CustomEvent<{ value: string, total: number }>} ev */
    pagerUpdate({ detail }) {
        this.state.value = detail.value;
        this.state.total = detail.total;
        browser.clearTimeout(this.startShowTimer);
        this.state.show = true;
        this.startShowTimer = browser.setTimeout(() => {
            this.state.show = false;
        }, 1400);
    }
}

registry.category("main_components").add("PagerIndicator", {
    Component: PagerIndicator,
});
