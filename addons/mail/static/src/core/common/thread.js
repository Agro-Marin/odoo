/** @odoo-module native */
import { DateSection } from "@mail/core/common/date_section";
import { Message } from "@mail/core/common/message";
import { useThreadScroll } from "@mail/core/common/thread_scroll_hook";
import { useVisible } from "@mail/utils/common/hooks";
import { markThreadAsReadIfAtBottom } from "@mail/utils/common/thread_read";
import {
    Component,
    markRaw,
    onMounted,
    onWillUnmount,
    onWillUpdateProps,
    reactive,
    toRaw,
    useChildSubEnv,
    useEffect,
    useRef,
    useState,
} from "@odoo/owl";
import { Transition } from "@web/components/transition";
import { browser } from "@web/core/browser/browser";
import { useBus, useRefListener, useService } from "@web/core/utils/hooks";
import { useThrottleForAnimation } from "@web/core/utils/timing";

import { NotificationMessage } from "./notification_message.js";

export const PRESENT_VIEWPORT_THRESHOLD = 1;
/**
 * @typedef {Object} Props
 * @property {boolean} [isInChatWindow=false]
 * @property {number} [jumpPresent=0]
 * @property {number} [jumpToNewMessage=0]
 * @property {"asc"|"desc"} [order="asc"]
 * @property {import("models").Thread} thread
 * @property {string} [searchTerm]
 * @property {import("@web/core/utils/hooks").Ref} [scrollRef]
 * @extends {Component<Props, Env>}
 */
export class Thread extends Component {
    static components = { Message, NotificationMessage, Transition, DateSection };
    static props = [
        "autofocus?",
        "showDates?",
        "isInChatWindow?",
        "jumpPresent?",
        "jumpToNewMessage?",
        "thread",
        "order?",
        "scrollRef?",
        "showEmptyMessage?",
        "showJumpPresent?",
        "messageActions?",
    ];
    static defaultProps = {
        isInChatWindow: false,
        jumpPresent: 0,
        order: "asc",
        showDates: true,
        showEmptyMessage: true,
        showJumpPresent: true,
        messageActions: true,
    };
    static template = "mail.Thread";

    setup() {
        super.setup();
        // Throttled: the handler does several layout reads and a reactive
        // record write, way too much work for every native scroll tick.
        this.onScroll = useThrottleForAnimation(this.onScroll);
        this.registerMessageRef = this.registerMessageRef.bind(this);
        this.store = useService("mail.store");
        this.ui = useService("ui");
        this.state = useState({
            isReplyingTo: false,
            mountedAndLoaded: false,
            /**
             * Bumped by the scroll machine's reset (see the `onReset` option of
             * `useThreadScroll`). Used as a dependency of the effect mirroring
             * `isLoaded` into `mountedAndLoaded` so the mirror is re-synced after
             * a reset without making `mountedAndLoaded` depend on itself.
             */
            resetCount: 0,
            showJumpPresent: false,
            scrollTop: null,
        });
        this.lastJumpPresent = this.props.jumpPresent;
        this.orm = useService("orm");
        /** @type {ReturnType<import('@mail/utils/common/hooks').useMessageScrolling>|null} */
        this.messageHighlight = this.env.messageHighlight
            ? useState(this.env.messageHighlight)
            : null;
        this.scrollingToHighlight = false;
        this.refByMessageId = reactive(new Map(), () => {
            this.scrollToHighlighted();
        });
        useEffect(
            () => {
                this.scrollToHighlighted();
            },
            () => [this.messageHighlight?.highlightedMessageId],
        );
        this.jumpPresentRef = useRef("jump-present");
        this.root = useRef("messages");
        this.visibleState = useVisible("messages", () => {
            this.updateShowJumpPresent();
        });
        /**
         * This is the reference element with the scrollbar. The reference can
         * either be the chatter scrollable (if chatter) or the thread
         * scrollable (in other cases).
         */
        this.scrollableRef = this.props.scrollRef ?? this.root;
        useRefListener(
            this.scrollableRef,
            "scrollend",
            () => (this.state.scrollTop = this.scrollableRef.el.scrollTop),
        );
        this.presentThresholdState = useVisible("present-treshold", () =>
            this.updateShowJumpPresent(),
        );
        this.threadScroll = useThreadScroll({
            scrollableRef: this.scrollableRef,
            getThread: () => this.props.thread,
            getOrder: () => this.props.order,
            getMountedAndLoaded: () => this.state.mountedAndLoaded,
            getMessageHighlight: () => this.messageHighlight,
            getHighlightedMessageId: () =>
                this.env.messageHighlight?.highlightedMessageId,
            // Routed through the component method so patches/subclasses can
            // override the contextual step of the pipeline.
            applyScrollContextually: (thread) => this.applyScrollContextually(thread),
            onReset: () => {
                this.state.mountedAndLoaded = false;
                // Bump `resetCount` (a mirror-effect dependency) so the effect
                // re-runs and re-syncs `mountedAndLoaded`. Only when loaded:
                // while `!isLoaded`, `applyScroll` resets on every patch, so an
                // unconditional bump would spin the render loop until the fetch
                // resolves. When loaded the bump re-renders once, the mirror
                // sets `mountedAndLoaded` true and `applyScroll` stops
                // resetting, so it converges.
                if (this.props.thread.isLoaded) {
                    this.state.resetCount++;
                }
            },
            onResize: () => this.computeJumpPresentPosition(),
            onScroll: this.onScroll,
        });
        useChildSubEnv({
            getCurrentThread: () => this.props.thread,
            onImageLoaded: this.threadScroll.applyScroll,
        });
        useEffect(
            (focus) => {
                if (focus && this.state.mountedAndLoaded) {
                    this.root.el.focus();
                }
            },
            () => [
                this.props.autofocus + this.props.thread.autofocus,
                this.state.mountedAndLoaded,
            ],
        );
        useEffect(
            () => {
                this.computeJumpPresentPosition();
            },
            () => [this.jumpPresentRef.el, this.viewportEl],
        );
        useEffect(
            () => this.updateShowJumpPresent(),
            () => [this.props.thread.loadNewer],
        );
        useEffect(
            () => {
                if (this.props.jumpPresent !== this.lastJumpPresent) {
                    this.jumpToPresent({ immediate: true });
                }
            },
            () => [this.props.jumpPresent],
        );
        useEffect(
            () => {
                if (this.props.thread.highlightMessage && this.state.mountedAndLoaded) {
                    this.messageHighlight?.highlightMessage(
                        this.props.thread.highlightMessage,
                        this.props.thread,
                    );
                    this.props.thread.highlightMessage = null;
                }
            },
            () => [this.props.thread.highlightMessage, this.state.mountedAndLoaded],
        );
        useEffect(
            () => {
                if (!this.state.mountedAndLoaded) {
                    return;
                }
                this.updateShowJumpPresent();
            },
            () => [this.state.mountedAndLoaded],
        );
        onMounted(() => {
            if (!this.env.chatter || this.env.chatter?.fetchMessages) {
                if (this.env.chatter) {
                    this.env.chatter.fetchMessages = false;
                }
                this.fetchMessages();
            }
        });
        onWillUnmount(() => {
            if (this.props.thread.isFocusedByThread) {
                this.props.thread.isFocusedByThread = false;
            }
        });
        useEffect(
            (isLoaded) => {
                this.state.mountedAndLoaded = isLoaded;
            },
            /**
             * The scroll reset forces `mountedAndLoaded` false and this effect
             * writes it too, so it can't be its own dependency: `useEffect`
             * records dependencies before running the body, hence a reset
             * landing while this effect is being applied would leave the
             * recorded value matching the current one and strand
             * `mountedAndLoaded` at false. Depend on `resetCount`, bumped by
             * the reset, so every reset re-syncs `mountedAndLoaded` with
             * `isLoaded`.
             */
            () => [this.props.thread.isLoaded, this.state.resetCount],
        );
        useEffect(
            () => {
                if (!this.props.jumpToNewMessage) {
                    return;
                }
                const separatorId = this.props.thread.newMessageSeparatorId;
                if (!separatorId) {
                    return;
                }
                // Message ids form a global sequence, so the message of id
                // `separatorId - 1` almost never belongs to this thread. Jump
                // to the last message of the thread before the separator (=
                // the message with the greatest id strictly below it).
                let jumpMessage;
                for (const message of this.props.thread.messages) {
                    if (
                        Number.isInteger(message.id) &&
                        message.id < separatorId &&
                        (!jumpMessage || message.id > jumpMessage.id)
                    ) {
                        jumpMessage = message;
                    }
                }
                const el = jumpMessage
                    ? this.refByMessageId.get(jumpMessage.id)?.el
                    : undefined;
                if (el) {
                    el.querySelector(".o-mail-Message-jumpTarget").scrollIntoView({
                        behavior: "instant",
                        block: "center",
                    });
                }
            },
            () => [this.props.jumpToNewMessage],
        );
        useBus(this.env.bus, "MAIL:RELOAD-THREAD", ({ detail }) => {
            const { model, id } = this.props.thread;
            if (detail.model === model && detail.id === id) {
                toRaw(this.props.thread).fetchNewMessages();
            }
        });
        onWillUpdateProps((nextProps) => {
            if (nextProps.thread.notEq(this.props.thread)) {
                this.lastJumpPresent = nextProps.jumpPresent;
            }
            if (!this.env.chatter || this.env.chatter?.fetchMessages) {
                if (this.env.chatter) {
                    this.env.chatter.fetchMessages = false;
                }
                toRaw(nextProps.thread).fetchNewMessages();
            }
        });
    }

    computeJumpPresentPosition() {
        if (!this.viewportEl || !this.jumpPresentRef.el) {
            return;
        }
        const width = this.viewportEl.clientWidth;
        const height = this.viewportEl.clientHeight;
        const computedStyle = window.getComputedStyle(this.viewportEl);
        const ps = parseInt(computedStyle.getPropertyValue("padding-left"));
        const pe = parseInt(computedStyle.getPropertyValue("padding-right"));
        const pt = parseInt(computedStyle.getPropertyValue("padding-top"));
        const pb = parseInt(computedStyle.getPropertyValue("padding-bottom"));
        this.jumpPresentRef.el.style.transform = `translate(${
            this.env.inChatter ? 22 : width - ps - pe - 22
        }px, ${
            this.env.inChatter && !this.env.inChatter.aside
                ? -22
                : height - pt - pb - (this.env.inChatter?.aside ? 75 : 0)
        }px)`;
    }

    /**
     * Contextual step of the scroll pipeline: how the scroll position must be
     * adjusted for the current render (the "5 behaviors" documented on
     * `ThreadScroll` in @mail/core/common/thread_scroll_hook). Kept as a
     * component method purely as the override seam: `useThreadScroll` routes
     * the pipeline through this method so patches and subclasses (e.g. discuss
     * scrolling to the first unread message) can intercept it mid-pipeline.
     *
     * @param {import("models").Thread} thread
     */
    applyScrollContextually(thread) {
        this.threadScroll.applyScrollContextually(thread);
    }

    /** @type {import("@mail/core/common/thread_scroll_hook").ThreadScroll["isSmoothScrolling"]} */
    get isSmoothScrolling() {
        return this.threadScroll.isSmoothScrolling;
    }

    /** @type {import("@mail/core/common/thread_scroll_hook").ThreadScroll["smoothScrollingDeferred"]} */
    get smoothScrollingDeferred() {
        return this.threadScroll.smoothScrollingDeferred;
    }

    fetchMessages() {
        toRaw(this.props.thread).fetchNewMessages();
    }

    get viewportEl() {
        let viewportEl = this.scrollableRef.el;
        if (viewportEl && viewportEl.clientHeight > browser.innerHeight) {
            while (viewportEl && viewportEl.clientHeight > browser.innerHeight) {
                viewportEl = viewportEl.parentElement;
            }
        }
        return viewportEl;
    }

    get PRESENT_THRESHOLD() {
        const threshold =
            (this.viewportEl?.clientHeight ?? 0) * PRESENT_VIEWPORT_THRESHOLD;
        return this.state.showJumpPresent ? threshold - 200 : threshold;
    }

    updateShowJumpPresent() {
        this.state.showJumpPresent =
            this.visibleState.isVisible &&
            (this.props.thread.loadNewer ||
                this.presentThresholdState.isVisible === false);
    }

    onClickLoadOlder() {
        this.props.thread.fetchMoreMessages();
    }

    async onClickPreferences() {
        const actionDescription = await this.orm.call("res.users", "action_get");
        actionDescription.res_id = this.store.self.main_user_id?.id;
        this.env.services.action.doAction(actionDescription);
    }

    onFocusin() {
        this.props.thread.isFocusedByThread = true;
        markThreadAsReadIfAtBottom(this.props.thread);
    }

    onFocusout() {
        this.props.thread.isFocusedByThread = false;
    }

    async onParentMessageClick(parentMessage) {
        if (!parentMessage) {
            return;
        }
        const targetThread = parentMessage.thread;
        if (!targetThread) {
            return;
        }
        if (targetThread.eq(this.props.thread)) {
            this.env.messageHighlight?.highlightMessage(parentMessage, targetThread);
        } else {
            targetThread.highlightMessage = parentMessage;
            await targetThread.open({ focus: true });
        }
    }

    getMessageClassName(message) {
        return !message.isNotification &&
            this.messageHighlight?.highlightedMessageId === message.id
            ? "o-highlighted bg-view shadow-lg pb-1"
            : "";
    }

    async jumpToPresent({ immediate = false } = {}) {
        this.messageHighlight?.clear();
        if (!immediate || this.props.thread.loadNewer) {
            await this.props.thread.loadAround();
            this.props.thread.loadNewer = false;
            this.state.showJumpPresent = false;
        }
        this.props.thread.scrollTop = immediate ? "bottom" : "bottom-smooth";
        if (!this.ui.isSmall) {
            this.props.thread.composer.autofocus++;
        }
    }

    registerMessageRef(message, ref) {
        if (!ref) {
            this.refByMessageId.delete(message.id);
            return;
        }
        this.refByMessageId.set(message.id, markRaw(ref));
    }

    isSquashed(msg, prevMsg) {
        if (this.props.thread.isMailbox) {
            return false;
        }
        if (!prevMsg || prevMsg.message_type === "notification" || this.env.inChatter) {
            return false;
        }

        if (!msg.author?.eq(prevMsg.author)) {
            return false;
        }
        if (!msg.thread?.eq(prevMsg.thread)) {
            return false;
        }
        if (msg.isNote) {
            return false;
        }
        return msg.datetime.ts - prevMsg.datetime.ts < 5 * 60 * 1000;
    }

    onScroll() {
        if (!this.scrollableRef.el) {
            // rAF-throttled: can fire after the scrollable is unmounted.
            return;
        }
        this.threadScroll.saveScroll();
        // Also mirror scrollTop into the reactive state from here: the
        // dedicated "scrollend" listener never fires on Safari.
        this.state.scrollTop = this.scrollableRef.el.scrollTop;
        markThreadAsReadIfAtBottom(this.props.thread);
    }

    async scrollToHighlighted() {
        if (!this.messageHighlight?.highlightedMessageId || this.scrollingToHighlight) {
            return;
        }
        const el = this.refByMessageId.get(
            this.messageHighlight.highlightedMessageId,
        )?.el;
        if (el) {
            this.scrollingToHighlight = true;

            await this.messageHighlight.startupDeferred;
            this.messageHighlight
                .scrollTo(el.querySelector(".o-mail-Message-jumpTarget"))
                .then(() => (this.scrollingToHighlight = false));
        }
    }

    get orderedMessages() {
        const messages = this.state.mountedAndLoaded
            ? this.props.thread.messages
            : this.props.thread.phantomMessages;
        return this.props.order === "asc" ? [...messages] : [...messages].reverse();
    }

    get showLoadOlder() {
        return (
            this.props.thread.loadOlder &&
            this.props.thread.isLoaded &&
            !this.props.thread.isTransient &&
            !this.props.thread.hasLoadingFailed &&
            !this.messageHighlight?.initiated &&
            !this.messageHighlight?.highlightedMessageId
        );
    }

    /**
     * Kept as a component method as an override/consumer seam (patches and
     * tests target it); the smooth-scrolling machinery lives on the hook.
     *
     * @type {import("@mail/core/common/thread_scroll_hook").ThreadScroll["setScroll"]}
     */
    setScroll(value, options) {
        this.threadScroll.setScroll(value, options);
    }

    get showStartMessage() {
        return (
            this.state.mountedAndLoaded &&
            this.props.thread.hasStartOfConversationBanner
        );
    }

    get startMessageTitle() {
        return this.props.thread.conversationStartTitle;
    }

    get startMessageSubtitle() {
        return this.props.thread.conversationStartSubtitle;
    }
}
