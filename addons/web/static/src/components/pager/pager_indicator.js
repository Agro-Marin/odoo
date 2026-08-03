// @ts-check
/** @odoo-module native */

/** @module @web/components/pager/pager_indicator */

import { Component, onWillUnmount, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { Transition } from "@web/core/transition";
import { useBus } from "@web/core/utils/hooks";

import { PAGER_UPDATED_EVENT, pagerBus } from "./pager.js";

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
        useBus(pagerBus, PAGER_UPDATED_EVENT, this.pagerUpdate);
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
