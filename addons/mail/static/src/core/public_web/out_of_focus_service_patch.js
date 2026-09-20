// @ts-check
/** @odoo-module native */
import {
    OutOfFocusService,
    outOfFocusService,
} from "@mail/core/common/out_of_focus_service";
import { makeLogger } from "@web/core/debug/debug_logger";
import { patch } from "@web/core/utils/patch";

const log = makeLogger("mail.out_of_focus");
patch(OutOfFocusService.prototype, {
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {import("services").ServiceFactories} services
     */
    setup(env, services) {
        super.setup(env, services);
        this.titleService = services.title;
        this.counter = 0;
        this.contributingMessageLocalIds = new Set();
        env.bus.addEventListener("window_focus", () => this.onWindowFocus());
    },
    clearUnreadMessage() {
        log.logic("clearUnreadMessage", () => ({ counter: this.counter }));
        this.counter = 0;
        this.contributingMessageLocalIds.clear();
        this.titleService.setCounters({ discuss: undefined });
    },
    /**
     * @param {import("models").Message} message
     * @param {import("models").Thread} [thread]
     */
    async notify(message, thread) {
        if (this.contributingMessageLocalIds.has(message.localId)) {
            log.logic("notify dedup", () => ({ message: message.localId }));
            return;
        }
        this.contributingMessageLocalIds.add(message.localId);
        this.counter++;
        log.logic("title counter", () => ({ counter: this.counter }));
        this.titleService.setCounters({ discuss: this.counter });
        return super.notify(message, thread);
    },
    onWindowFocus() {
        this.clearUnreadMessage();
    },
});
outOfFocusService.dependencies = [...outOfFocusService.dependencies, "title"];
