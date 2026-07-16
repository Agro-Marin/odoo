/** @odoo-module native */
import {
    Component,
    onMounted,
    onPatched,
    status,
    useExternalListener,
    useRef,
} from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
/**
 * @typedef {Object} Props
 * @property {import("models").RtcSession} session
 * @extends {Component<Props, Env>}
 */
export class CallParticipantVideo extends Component {
    static props = ["session", "type", "inset?"];
    static template = "discuss.CallParticipantVideo";

    setup() {
        super.setup();
        this.rtc = useService("discuss.rtc");
        this.store = useService("mail.store");
        this.root = useRef("root");
        onMounted(() => this._update());
        onPatched(() => this._update());
        useExternalListener(this.env.bus, "RTC-SERVICE:PLAY_MEDIA", async () => {
            await this.play();
        });
    }

    _update() {
        if (!this.root.el) {
            return;
        }
        const stream = this.props.session?.getStream(this.props.type);
        const srcObject = stream ?? null;
        if (this.root.el.srcObject === srcObject) {
            // onPatched runs on EVERY parent re-render (talking indicators,
            // overlay toggles): reassigning the same stream and calling
            // load() restarts the media pipeline — decode reset and a
            // black-frame flicker per render during the call
            return;
        }
        this.root.el.srcObject = srcObject;
        this.root.el.load();
    }

    async play() {
        try {
            await this.root.el?.play?.();
            this.props.session.videoError = undefined;
        } catch (error) {
            if (status(this) === "destroyed") {
                return;
            }
            this.props.session.videoError = error.name;
        }
    }

    async onVideoLoadedMetaData() {
        await this.play();
    }
}
