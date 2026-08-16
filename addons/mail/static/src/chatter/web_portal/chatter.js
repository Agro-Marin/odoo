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
 * @property {boolean} [composer=true]
 * @property {number|false} [threadId=false]
 * @property {string} threadModel
 * @property {boolean} [twoColumns=false]
 */
/**
 * @typedef {Object} State
 * @property {number} jumpThreadPresent
 * @property {import("models").Thread} thread
 * @property {boolean} aside
 * @property {boolean} disabled
 * @property {boolean} [isTopStickyPinned]
 */
/**
 * @template {Props} [P=Props]
 * @template {State} [S=State]
 * @extends {Component<P, import("@web/env").OdooEnv>}
 */
export class Chatter extends Component {
    static template = "mail.Chatter";
    static components = { Thread, Composer };
    static props = ["composer?", "threadId?", "threadModel", "twoColumns?"];
    static defaultProps = { composer: true, threadId: false, twoColumns: false };

    setup() {
        this.store = useService("mail.store");
        /** @type {S} */
        this.state = /** @type {S} */ (
            useState({
                jumpThreadPresent: 0,
                /** @type {import("models").Thread} */
                thread: undefined,
                aside: false,
                disabled: !this.props.threadId,
            })
        );
        this.rootRef = useRef("root");
        this.onScrollDebounced = useThrottleForAnimation(this.onScroll);
        useChildSubEnv(this.childSubEnv);

        onMounted(this._onMounted);
        onWillUpdateProps(
            /** @param {{threadModel: string, threadId: number|false}} nextProps */
            (nextProps) => {
                this.state.disabled = !nextProps.threadId;
                const threadChanged =
                    this.props.threadId !== nextProps.threadId ||
                    this.props.threadModel !== nextProps.threadModel;
                if (threadChanged) {
                    this.changeThread(nextProps.threadModel, nextProps.threadId);
                }
                const staleDataRequested = this.env.chatter
                    ? this.env.chatter.fetchThreadData
                    : true;
                if (this.env.chatter) {
                    this.env.chatter.fetchThreadData = false;
                }
                if (threadChanged || staleDataRequested) {
                    this.load(this.state.thread, this.requestList);
                }
            },
        );
    }

    get afterPostRequestList() {
        return ["messages"];
    }

    get childSubEnv() {
        return { inChatter: this.state };
    }

    /** @returns {string[]} */
    get onCloseFullComposerRequestList() {
        return ["messages"];
    }

    /** @returns {string[]} */
    get requestList() {
        return [];
    }

    /**
     * @param {string} threadModel
     * @param {number|false} threadId
     */
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
                        authorModelName === "res.partner"
                            ? /** @type {import("models").ResPartner} */ (effectiveSelf)
                            : undefined,
                    author_guest_id:
                        authorModelName === "mail.guest"
                            ? /** @type {import("models").MailGuest} */ (effectiveSelf)
                            : undefined,
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
        this.load(this.state.thread, this.afterPostRequestList);
    }

    onScroll() {
        this.state.isTopStickyPinned = this.rootRef.el.scrollTop !== 0;
    }
}
