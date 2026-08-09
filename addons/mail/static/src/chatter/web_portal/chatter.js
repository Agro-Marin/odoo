/** @odoo-module native */
import { Composer } from "@mail/core/common/composer";
import { Thread } from "@mail/core/common/thread";
import {
    Component,
    onMounted,
    onWillUpdateProps,
    useChildSubEnv,
    useRef,
    useState,
} from "@odoo/owl";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { useThrottleForAnimation } from "@web/core/utils/timing";
/**
 * @typedef {Object} Props
 * @extends {Component<Props, Env>}
 */
export class Chatter extends Component {
    static template = "mail.Chatter";
    static components = { Thread, Composer };
    static props = ["composer?", "threadId?", "threadModel", "twoColumns?"];
    static defaultProps = { composer: true, threadId: false, twoColumns: false };

    setup() {
        this.store = useService("mail.store");
        this.state = useState({
            jumpThreadPresent: 0,
            /** @type {import("models").Thread} */
            thread: undefined,
            aside: false,
            disabled: !this.props.threadId,
        });
        this.rootRef = useRef("root");
        this.onScrollDebounced = useThrottleForAnimation(this.onScroll);
        useChildSubEnv(this.childSubEnv);

        onMounted(this._onMounted);
        onWillUpdateProps((nextProps) => {
            this.state.disabled = !nextProps.threadId;
            const threadChanged =
                this.props.threadId !== nextProps.threadId ||
                this.props.threadModel !== nextProps.threadModel;
            if (threadChanged) {
                this.changeThread(nextProps.threadModel, nextProps.threadId);
            }
            // Two independent reasons to fetch, and they must stay independent.
            // `env.chatter.fetchThreadData` is a *shared* flag the form
            // controller raises before every root load and the first chatter
            // render to observe it clears; it covers "same thread, its data may
            // be stale after a save". It cannot also stand in for "the thread
            // changed": a render that consumes the flag before the new
            // `threadId` arrives leaves the switch itself unfetched, which is
            // how paging to another record showed the previous record's
            // followers, activities and scheduled messages. A new thread has no
            // data by construction, so that case answers for itself.
            const staleDataRequested = this.env.chatter
                ? this.env.chatter.fetchThreadData
                : true;
            if (this.env.chatter) {
                this.env.chatter.fetchThreadData = false;
            }
            if (threadChanged || staleDataRequested) {
                this.load(this.state.thread, this.requestList);
            }
        });
    }

    get afterPostRequestList() {
        return ["messages"];
    }

    get childSubEnv() {
        return { inChatter: this.state };
    }

    get onCloseFullComposerRequestList() {
        return ["messages"];
    }

    get requestList() {
        return [];
    }

    changeThread(threadModel, threadId) {
        this.state.thread = this.store.Thread.insert({
            model: threadModel,
            id: threadId,
        });
        if (threadId === false) {
            if (this.state.thread.messages.length === 0) {
                const { effectiveSelf } = this.state.thread;
                const authorModelName = effectiveSelf.Model.getName();
                this.state.thread.messages.push({
                    id: this.store.getNextTemporaryId(),
                    author_id:
                        authorModelName === "res.partner" ? effectiveSelf : undefined,
                    author_guest_id:
                        authorModelName === "mail.guest" ? effectiveSelf : undefined,
                    body: _t("Creating a new record..."),
                    message_type: "notification",
                    thread: this.state.thread,
                    trackingValues: [],
                    res_id: threadId,
                    model: threadModel,
                });
            }
        }
    }

    /**
     * Fetch data for the thread according to the request list.
     * @param {import("models").Thread} thread
     * @param {string[]} requestList
     */
    async load(thread, requestList) {
        if (!thread.id || !this.state.thread?.eq(thread)) {
            return;
        }
        await thread.fetchThreadData(requestList);
    }

    onCloseFullComposerCallback() {
        this.load(this.state.thread, this.onCloseFullComposerRequestList);
    }

    _onMounted() {
        this.changeThread(this.props.threadModel, this.props.threadId);
        if (!this.env.chatter || this.env.chatter?.fetchThreadData) {
            if (this.env.chatter) {
                this.env.chatter.fetchThreadData = false;
            }
            this.load(this.state.thread, this.requestList);
        }
    }

    onPostCallback() {
        this.state.jumpThreadPresent++;
        // Load new messages to fetch potential new messages from other users (useful due to lack of auto-sync in chatter).
        this.load(this.state.thread, this.afterPostRequestList);
    }

    onScroll() {
        this.state.isTopStickyPinned = this.rootRef.el.scrollTop !== 0;
    }
}
