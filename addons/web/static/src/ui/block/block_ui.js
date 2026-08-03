// @ts-check
/** @odoo-module native */

/** @module @web/ui/block/block_ui */

import { Component, onWillDestroy, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { AppEvent } from "@web/core/events";
import { _t } from "@web/core/translation";
import { useBus, useService } from "@web/core/utils/hooks";

const BLOCK_STATES = { UNBLOCKED: 0, BLOCKED: 1, VISIBLY_BLOCKED: 2 };

/**
 * `time` is the wait before the NEXT message, not the elapsed total; `null`
 * ends the chain. `_t` is lazy, so translation still resolves per user.
 */
const MESSAGES_BY_DURATION = [
    { time: 20, l1: _t("Loading...") },
    { time: 40, l1: _t("Still loading...") },
    {
        time: 60,
        l1: _t("Still loading..."),
        l2: _t("Please be patient."),
    },
    {
        time: 120,
        l1: _t("Don't leave yet,"),
        l2: _t("it's still loading..."),
    },
    {
        time: 180,
        l1: _t("You may not believe it,"),
        l2: _t("but the application is actually loading..."),
    },
    {
        time: 3180,
        l1: _t("Take a minute to get a coffee,"),
        l2: _t("because it's loading..."),
    },
    {
        time: null,
        l1: _t("Maybe you should consider reloading the application by pressing F5..."),
    },
];

export class BlockUI extends Component {
    static props = {};

    static template = "web.BlockUI";

    /** @type {number | undefined} */
    showBlockedUITimer;
    /** @type {number | undefined} */
    msgTimer;

    setup() {
        this.messagesByDuration = MESSAGES_BY_DURATION;
        this.BLOCK_STATES = BLOCK_STATES;
        this.state = useState({
            blockState: BLOCK_STATES.UNBLOCKED,
            line1: "",
            line2: "",
        });

        const { bus } = useService("ui");
        useBus(bus, AppEvent.BLOCK, this.block);
        useBus(bus, AppEvent.UNBLOCK, this.unblock);

        onWillDestroy(() => {
            browser.clearTimeout(this.showBlockedUITimer);
            browser.clearTimeout(this.msgTimer);
        });
    }

    /** @param {number} index */
    replaceMessage(index) {
        const message = MESSAGES_BY_DURATION[index];
        this.state.line1 = message.l1;
        this.state.line2 = message.l2 || "";
        if (message.time !== null) {
            this.msgTimer = browser.setTimeout(() => {
                this.replaceMessage(index + 1);
            }, message.time * 1000);
        }
    }

    /** @param {CustomEvent<{ delay?: number, message?: string } | undefined>} ev */
    block(ev) {
        const showBlockedUI = () => {
            this.state.blockState = this.BLOCK_STATES.VISIBLY_BLOCKED;
            if (!ev.detail?.message) {
                this.replaceMessage(0);
            }
        };
        if (ev.detail?.message) {
            this.state.line1 = ev.detail.message;
        }
        const delay = ev.detail?.delay;
        if (delay) {
            this.state.blockState = this.BLOCK_STATES.BLOCKED;
            this.showBlockedUITimer = browser.setTimeout(showBlockedUI, delay);
        } else {
            showBlockedUI();
        }
    }

    unblock() {
        this.state.blockState = this.BLOCK_STATES.UNBLOCKED;
        browser.clearTimeout(this.showBlockedUITimer);
        browser.clearTimeout(this.msgTimer);
        this.state.line1 = "";
        this.state.line2 = "";
    }
}
