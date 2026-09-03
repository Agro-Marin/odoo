/** @odoo-module native */
import { AvatarStack } from "@mail/discuss/core/common/avatar_stack";

import { Component, useState } from "@odoo/owl";

import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";

export class CallPresentationBar extends Component {
    static template = "discuss.CallPresentationBar";
    static props = {};
    static components = { AvatarStack };

    setup() {
        this.rtc = useService("discuss.rtc");
        this.presentationAudio = useState({
            enabled: this.rtc.state.screenAudioTrack?.enabled,
        });
    }

    get presenterPersonas() {
        return this.presenterSessions.map((session) => session.channel_member_id.persona);
    }

    /** Own session first, so the labels can lead with "You". */
    get presenterSessions() {
        const sessions = this.rtc.channel.rtc_session_ids.filter(
            (session) => session.is_screen_sharing_on,
        );
        if (!this.rtc.selfSession.is_screen_sharing_on) {
            return sessions;
        }
        return [
            this.rtc.selfSession,
            ...sessions.filter((session) => session.notEq(this.rtc.selfSession)),
        ];
    }

    get presenterText() {
        const names = this.presenterSessions.map((session) => session.channel_member_id.name);
        const count = names.length;
        if (this.rtc.selfSession.is_screen_sharing_on) {
            if (count === 1) {
                return _t("You are presenting");
            }
            if (count === 2) {
                return _t("You and %(name)s are presenting", { name: names[1] });
            }
            return _t("You, %(name)s and %(count)s more are presenting", {
                name: names[1],
                count: count - 2,
            });
        }
        if (count === 1) {
            return _t("%(name)s is presenting", { name: names[0] });
        }
        if (count === 2) {
            return _t("%(name_1)s and %(name_2)s are presenting", {
                name_1: names[0],
                name_2: names[1],
            });
        }
        return _t("%(name_1)s, %(name_2)s and %(count)s more are presenting", {
            name_1: names[0],
            name_2: names[1],
            count: count - 2,
        });
    }

    togglePresentationAudio() {
        this.rtc.state.screenAudioTrack.enabled = !this.rtc.state.screenAudioTrack.enabled;
        this.presentationAudio.enabled = this.rtc.state.screenAudioTrack.enabled;
    }

    stopPresenting() {
        // Our toggleVideo takes an options object: passing a bare `false` (as
        // upstream does) would land as `{}` and merely toggle.
        this.rtc.toggleVideo("screen", { force: false });
    }
}
