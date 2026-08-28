/** @odoo-module native */
import { parseVersion } from "@mail/utils/common/misc";
import { markRaw, markup, reactive } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
const INITIAL_RELEASE_TIMEOUT = 750;
const COMMON_RELEASE_TIMEOUT = 200;
const EXT_ID = "mdiacebcbkmjjlpclnbcgiepgifcnpmg";

export const pttExtensionServiceInternal = {
    /** @param {{isEnabled: boolean|undefined}} pttService */
    onAnswerIsEnabled(pttService) {
        pttService.isEnabled = true;
    },
};

export class PttExtensionService {
    /**
     * @param {import("@web/env").OdooEnv} env
     */
    constructor(env) {
        this.env = env;
        this.isEnabled = undefined;
        this.voiceActivated = undefined;
        this.downloadURL = `https://chromewebstore.google.com/detail/discuss-push-to-talk/${EXT_ID}`;
        // markRaw: reactive() would proxy the promise, and awaiting a proxied
        // promise calls then() on an incompatible receiver.
        this.versionPromise = markRaw(
            window.chrome?.runtime
                ?.sendMessage(EXT_ID, { type: "ask-version" })
                .catch(() => "1.0.0.0") ?? Promise.resolve("1.0.0.0"),
        );
    }

    setup() {
        browser.addEventListener(
            "message",
            /** @param {MessageEvent} ev */ (ev) => this.onWindowMessage(ev),
        );
        this.sendMessage("ask-is-enabled");
    }

    get downloadText() {
        return _t(
            "The Push-to-Talk feature is only accessible within tab focus. To enable the Push-to-Talk functionality outside of this tab, we recommend downloading our %(anchor_start)sextension%(anchor_end)s.",
            {
                anchor_start: markup`<a href="${this.downloadURL}" target="_blank" class="text-reset text-decoration-underline">`,
                anchor_end: markup`</a>`,
            },
        );
    }

    /** @param {boolean} isTalking */
    notifyIsTalking(isTalking) {
        this.sendMessage("is-talking", isTalking);
    }

    subscribe() {
        this.voiceActivated = false;
        this.sendMessage("subscribe");
    }

    unsubscribe() {
        this.voiceActivated = false;
        this.sendMessage("unsubscribe");
    }

    /**
     * @param {"ask-is-enabled" | "subscribe" | "unsubscribe" | "is-talking"} type
     * @param {*} value
     */
    async sendMessage(type, value) {
        if (!this.isEnabled && type !== "ask-is-enabled") {
            return;
        }
        const version = parseVersion(await this.versionPromise);
        if (location.origin === "null") {
            return;
        }
        if (version.isLowerThan("1.0.0.2")) {
            window.postMessage({ from: "discuss", type, value }, location.origin);
            return;
        }
        window.chrome?.runtime?.sendMessage(EXT_ID, { type, value });
    }

    /** @param {MessageEvent} ev */
    onWindowMessage({ data, origin, source }) {
        const rtc = this.env.services["discuss.rtc"];
        if (
            source !== window ||
            origin !== location.origin ||
            data?.from !== "discuss-push-to-talk" ||
            (!rtc && data.type !== "answer-is-enabled")
        ) {
            return;
        }
        switch (data.type) {
            case "push-to-talk-pressed":
                this.onPushToTalkPressed(rtc);
                break;
            case "toggle-voice":
                this.onToggleVoice(rtc);
                break;
            case "answer-is-enabled":
                pttExtensionServiceInternal.onAnswerIsEnabled(this);
                break;
        }
    }

    onPushToTalkPressed(rtc) {
        this.voiceActivated = false;
        const isFirstPress = !rtc.selfSession?.isTalking;
        rtc.onPushToTalk();
        if (rtc.selfSession?.isTalking) {
            rtc.setPttReleaseTimeout(
                isFirstPress ? INITIAL_RELEASE_TIMEOUT : COMMON_RELEASE_TIMEOUT,
            );
        }
    }

    onToggleVoice(rtc) {
        if (!rtc.state.channel) {
            return;
        }
        if (this.voiceActivated) {
            rtc.setPttReleaseTimeout(0);
        } else {
            rtc.onPushToTalk();
        }
        this.voiceActivated = !this.voiceActivated;
    }
}

export const pttExtensionHookService = {
    /**
     * @param {import("@web/env").OdooEnv} env
     */
    start(env) {
        const ptt = reactive(new PttExtensionService(env));
        ptt.setup();
        return ptt;
    },
};

registry.category("services").add("discuss.ptt_extension", pttExtensionHookService);
