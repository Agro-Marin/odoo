/** @odoo-module native */
import { CallPreview } from "@mail/discuss/call/common/call_preview";
import { Component, useEffect, useState, useSubEnv } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
export class WelcomePage extends Component {
    static props = ["proceed?"];
    static template = "mail.WelcomePage";
    static components = { CallPreview };

    cameraPermissionOnMountChecked = false;

    setup() {
        super.setup();
        this.store = useService("mail.store");
        this.ui = useService("ui");
        this.rtc = useService("discuss.rtc");
        useSubEnv({ inWelcomePage: true });
        this.state = useState({
            userName: this.store.self_partner?.name || "",
            activateCamera: 0,
            activateMicrophone: 0,
            hasMicrophone: undefined,
            hasCamera: undefined,
        });
        useEffect(
            /**
             * @param {boolean} showCallPreview
             * @param {string} cameraPermission
             * @param {string} microphonePermission
             */
            (showCallPreview, cameraPermission, microphonePermission) => {
                if (!showCallPreview) {
                    return;
                }
                if (cameraPermission === "prompt" && !this.cameraPermissionOnMountChecked) {
                    this.rtc.showMediaPermissionDialog("camera");
                }
                // already allowed: light the devices up rather than making the
                // guest ask for them a second time on the preview
                if (cameraPermission === "granted") {
                    this.state.activateCamera++;
                }
                if (microphonePermission === "granted") {
                    this.state.activateMicrophone++;
                }
                this.cameraPermissionOnMountChecked = Boolean(cameraPermission);
            },
            () => [
                this.showCallPreview,
                this.rtc.cameraPermission,
                this.rtc.microphonePermission,
            ],
        );
    }

    get canJoin() {
        return Boolean(
            this.store.self_partner ||
                (this.state.userName.trim() && this.state.userName.length <= 60),
        );
    }

    get showCallPreview() {
        return this.store.discuss.thread.default_display_mode === "video_full_screen";
    }

    /** @param {KeyboardEvent} ev */
    onKeydownInput(ev) {
        if (ev.key === "Enter" && this.canJoin) {
            this.joinChannel();
        }
    }

    async joinChannel() {
        if (!this.store.self_partner) {
            await this.store.self_guest?.updateGuestName(this.state.userName.trim());
        }
        browser.localStorage.setItem(
            "discuss_call_preview_join_mute",
            !this.state.hasMicrophone,
        );
        browser.localStorage.setItem(
            "discuss_call_preview_join_video",
            Boolean(this.state.hasCamera),
        );
        this.props.proceed?.();
    }

    getLoggedInAsText() {
        return _t("Logged in as %s", this.store.self.name);
    }

    get noActiveParticipants() {
        return !this.store.discuss.thread.rtc_session_ids.length;
    }

    /** @param {{ microphone?: boolean, camera?: boolean }} settings */
    onCallSettingsChanged(settings) {
        if (settings.microphone !== undefined) {
            this.state.hasMicrophone = settings.microphone;
        }
        if (settings.camera !== undefined) {
            this.state.hasCamera = settings.camera;
        }
    }
}
