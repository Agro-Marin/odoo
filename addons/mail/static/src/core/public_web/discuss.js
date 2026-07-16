/** @odoo-module native */
import { DiscussContent } from "@mail/core/public_web/discuss_content";
import { DiscussSidebar } from "@mail/core/public_web/discuss_sidebar";
import { MessagingMenu } from "@mail/core/public_web/messaging_menu";
import { useMessageScrolling } from "@mail/utils/common/hooks";
import {
    Component,
    onMounted,
    onWillUnmount,
    useEffect,
    useExternalListener,
    useRef,
    useSubEnv,
} from "@odoo/owl";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { useService } from "@web/core/utils/hooks";
export class Discuss extends Component {
    static components = {
        DiscussContent,
        DiscussSidebar,
        MessagingMenu,
    };
    static props = {
        hasSidebar: { type: Boolean, optional: true },
        thread: { optional: true },
    };
    static defaultProps = { hasSidebar: true };
    static template = "mail.Discuss";

    setup() {
        super.setup();
        this.store = useService("mail.store");
        this.messageHighlight = useMessageScrolling();
        this.root = useRef("root");
        this.orm = useService("orm");
        this.effect = useService("effect");
        this.ui = useService("ui");
        useSubEnv({
            inDiscussApp: true,
            messageHighlight: this.messageHighlight,
        });
        useExternalListener(
            window,
            "keydown",
            (ev) => {
                if (
                    getActiveHotkey(ev) === "escape" &&
                    !this.thread?.composer?.isFocused
                ) {
                    if (this.thread?.composer) {
                        this.thread.composer.autofocus++;
                    }
                }
                if (getActiveHotkey(ev) === "control+k") {
                    this.store.env.services.command.openMainPalette({
                        searchValue: "@",
                    });
                    ev.preventDefault();
                    ev.stopPropagation();
                }
            },
            { capture: true },
        );
        if (this.store.inPublicPage) {
            useEffect(
                (thread, isSmall) => {
                    if (!thread) {
                        return;
                    }
                    if (isSmall) {
                        const promise = (this._openChatWindowPromise = this.thread
                            .openChatWindow({ focus: true })
                            .then((chatWindow) => {
                                if (this._openChatWindowPromise === promise) {
                                    this.chatWindow = chatWindow;
                                } else {
                                    // superseded while in flight: only the
                                    // latest window is tracked, an untracked
                                    // one could never be closed
                                    chatWindow?.close();
                                }
                            }));
                    } else {
                        this.chatWindow?.close();
                    }
                },
                () => [this.thread, this.ui.isSmall],
            );
        }
        onMounted(() => {
            document.body.classList.add("o_mail_discuss");
        });

        onWillUnmount(() => {
            document.body.classList.remove("o_mail_discuss");
        });
    }

    get thread() {
        return this.props.thread || this.store.discuss.thread;
    }
}
