// @ts-check
/** @odoo-module native */

/** @module @web/webclient/loading_indicator/loading_indicator - Loading indicator showing the count of active RPCs after a short display delay */

import { Component, onWillUnmount, useState } from "@odoo/owl";
import { Transition } from "@web/components/transition";
import { browser } from "@web/core/browser/browser";
import { RpcEvent } from "@web/core/events";
import { rpcBus } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { useBus } from "@web/core/utils/hooks";
/**
 * Shows a "Loading" rectangle with the count of running RPCs, after a 250ms
 * delay so short bursts of fast RPCs don't flash it.
 */
export class LoadingIndicator extends Component {
    static template = "web.LoadingIndicator";
    static components = { Transition };
    static props = {};

    setup() {
        this.state = useState({
            count: 0,
            show: false,
        });
        this.rpcIds = new Set();
        this.startShowTimer = null;
        useBus(rpcBus, RpcEvent.REQUEST, /** @type {any} */ (this.requestCall));
        useBus(rpcBus, RpcEvent.RESPONSE, /** @type {any} */ (this.responseCall));
        // Clear the pending 250ms show-timer if the component is destroyed
        // before it fires, so its callback can't run against a torn-down state.
        onWillUnmount(() => browser.clearTimeout(this.startShowTimer));
    }

    /** @param {{ detail: { settings: Object, data: { id: number } } }} ev */
    requestCall({ detail }) {
        // Defensive: malformed payloads (null detail, missing data/settings) can
        // reach the shared rpcBus from tests or synthetic fires. Guard like the
        // sibling listeners (currency_service, slow_rpc_service) so a bad event
        // is ignored instead of throwing inside the bus dispatch.
        if (!detail?.data || detail.settings?.silent) {
            return;
        }
        if (this.state.count === 0) {
            browser.clearTimeout(this.startShowTimer);
            this.startShowTimer = browser.setTimeout(() => {
                if (this.state.count) {
                    this.state.show = true;
                }
            }, 250);
        }
        this.rpcIds.add(detail.data.id);
        // Single source of truth (mirrors responseCall): the badge can never
        // desynchronize from the tracked ids, whatever an emitter does.
        this.state.count = this.rpcIds.size;
    }

    /** @param {{ detail: { settings: Object, data: { id: number } } }} ev */
    responseCall({ detail }) {
        // Same defensive guard as requestCall (see comment there).
        if (!detail?.data || detail.settings?.silent) {
            return;
        }
        this.rpcIds.delete(detail.data.id);
        this.state.count = this.rpcIds.size;
        if (this.state.count === 0) {
            browser.clearTimeout(this.startShowTimer);
            this.state.show = false;
        }
    }
}

registry.category("main_components").add("LoadingIndicator", {
    Component: LoadingIndicator,
});
