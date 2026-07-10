// @ts-check
/** @odoo-module native */

/** @module @web/webclient/loading_indicator/loading_indicator - Loading indicator counting active RPCs and blocking the UI after a 3s delay */

import { Component, useState } from "@odoo/owl";
import { Transition } from "@web/components/transition";
import { browser } from "@web/core/browser/browser";
import { RpcEvent } from "@web/core/events";
import { rpcBus } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { useBus } from "@web/core/utils/hooks";
/**
 * Shows a "Loading" rectangle with the count of running RPCs; blocks the UI
 * if an RPC is still pending after 3s.
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
    }

    /** @param {{ detail: { settings: Object, data: { id: number } } }} ev */
    requestCall({ detail }) {
        if (detail.settings.silent) {
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
        this.state.count++;
    }

    /** @param {{ detail: { settings: Object, data: { id: number } } }} ev */
    responseCall({ detail }) {
        if (detail.settings.silent) {
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
