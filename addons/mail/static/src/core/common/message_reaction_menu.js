/** @odoo-module native */
import { onExternalClick } from "@mail/utils/common/hooks";
import {
    Component,
    onMounted,
    useEffect,
    useExternalListener,
    useRef,
    useState,
} from "@odoo/owl";
import { loadEmoji } from "@web/components/emoji_picker/emoji_picker";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/ui/dialog/dialog";
export class MessageReactionMenu extends Component {
    static props = ["close", "message", "initialReaction?"];
    static components = { Dialog };
    static template = "mail.MessageReactionMenu";

    setup() {
        super.setup();
        this.root = useRef("root");
        this.store = useService("mail.store");
        this.ui = useService("ui");
        this.state = useState({
            reaction: this.props.initialReaction
                ? this.props.initialReaction
                : this.props.message.reactions[0],
        });
        useExternalListener(document, "keydown", this.onKeydown);
        onExternalClick("root", () => this.props.close());
        useEffect(
            () => {
                // length check first: with no reaction left, state.reaction
                // can be undefined (last reaction removed between the action
                // click and the dialog mount) and reading .content would
                // throw before the dialog closes itself
                if (this.props.message.reactions.length === 0) {
                    this.props.close();
                    return;
                }
                const activeReaction = this.props.message.reactions.find(
                    ({ content }) => content === this.state.reaction?.content,
                );
                if (!activeReaction) {
                    this.state.reaction = this.props.message.reactions[0];
                }
            },
            // signature over contents, not just length: a simultaneous
            // remove-of-A + add-of-C in one bus update keeps the length but
            // drops A's record (keyed by AND(message, content)), leaving
            // state.reaction pointing at a detached reaction
            () => [this.props.message.reactions.map((r) => r.content).join()],
        );
        onMounted(() => {
            if (!this.store.emojiLoader.loaded) {
                loadEmoji();
            }
        });
    }

    onKeydown(ev) {
        switch (ev.key) {
            case "Escape":
                this.props.close();
                break;
            case "q":
                this.props.close();
                break;
            default:
                return;
        }
    }

    getEmojiShortcode(reaction) {
        return (
            this.store.emojiLoader.loaded?.emojiValueToShortcodes?.[
                reaction.content
            ]?.[0] ?? "?"
        );
    }

    get contentClass() {
        const attClass = {
            "o-mail-MessageReactionMenu h-50 d-flex": true,
            "position-absolute bottom-0": this.store.useMobileView,
        };
        return Object.entries(attClass)
            .filter(([classNames, value]) => value)
            .map(([classNames]) => classNames)
            .join(" ");
    }
}
