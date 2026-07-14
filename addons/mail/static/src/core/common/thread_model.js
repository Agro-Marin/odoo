/** @odoo-module native */
import { AND, fields, Record } from "@mail/core/common/record";
import { applyCounterDelta, snapshotCounter } from "@mail/utils/common/counters";
import { useSequential } from "@mail/utils/common/hooks";
import { assignDefined } from "@mail/utils/common/misc";
import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";
import { Deferred } from "@web/core/utils/concurrency";
import { user } from "@web/services/user";
/**
 * @typedef SuggestedRecipient
 * @property {string} email
 * @property {import("models").Persona|false} persona
 * @property {string} lang
 * @property {string} reason
 */

export class Thread extends Record {
    static id = AND("model", "id");
    /**
     * @param {string} localId
     * @returns {string}
     */
    static localIdToActiveId(localId) {
        if (!localId) {
            return undefined;
        }
        // Transform "Thread,<model> AND <id>" to "<model>_<id>""
        return localId.split(",").slice(1).join("_").replace(" AND ", "_");
    }
    static async getOrFetch(data, fieldNames = []) {
        const thread = this.get(data);
        if (!(data.id > 0)) {
            return thread;
        }
        const store = this.store;
        const baseKey = `${data.model},${data.id}`;
        // Fields already requested once for which the server response came
        // back without a value are not requested again: a missing field would
        // otherwise trigger a refetch on every call, forever.
        const missingFieldNames = fieldNames.filter(
            (fieldName) =>
                thread?.[fieldName] === undefined &&
                !store._threadFetchAttempted.has(`${baseKey},${fieldName}`),
        );
        if (thread && missingFieldNames.length === 0) {
            return thread;
        }
        // In-flight dedup: concurrent callers requesting the same thread and
        // fields share a single promise (and a single RPC).
        const promiseKey = `${baseKey},${missingFieldNames.join(",")}`;
        const pending = store._threadFetchPromises.get(promiseKey);
        if (pending) {
            return pending;
        }
        const promise = (async () => {
            try {
                await store.fetchStoreData("mail.thread", {
                    thread_model: data.model,
                    thread_id: data.id,
                    request_list: missingFieldNames,
                });
            } finally {
                store._threadFetchPromises.delete(promiseKey);
            }
            const fetchedThread = this.get(data);
            if (!fetchedThread?.exists()) {
                return;
            }
            const stillMissing = missingFieldNames.filter(
                (fieldName) => fetchedThread[fieldName] === undefined,
            );
            if (stillMissing.length > 0) {
                for (const fieldName of stillMissing) {
                    store._threadFetchAttempted.add(`${baseKey},${fieldName}`);
                }
                console.warn(
                    `Thread.getOrFetch: fields [${stillMissing.join(", ")}] of thread ${baseKey} were requested but absent from the server response; they will not be requested again.`,
                );
            }
            return fetchedThread;
        })();
        store._threadFetchPromises.set(promiseKey, promise);
        return promise;
    }

    autofocus = 0;
    create_uid = fields.One("res.users");
    /** @type {number} */
    id;
    /** @type {string} */
    uuid;
    /** @type {string} */
    model;
    allMessages = fields.Many("mail.message", {
        inverse: "thread",
    });
    storeAsAllChannels = fields.One("Store", {
        compute() {
            if (this.isChannelKind) {
                return this.store;
            }
        },
        eager: true,
    });
    /**
     * Whether this thread is a discuss channel (any channel_type), i.e. a
     * conversation with members, rather than the message trail of a document.
     * Neutral default: plain document threads are not channels. The discuss
     * layer overrides this with the actual discriminator; base code must rely
     * on this predicate (or the more specific hooks below) instead of
     * comparing `this.model` to a hard-coded channel model name.
     *
     * @returns {boolean}
     */
    get isChannelKind() {
        return false;
    }
    /**
     * Whether this thread is strictly a 1:1 (or self) direct chat, excluding
     * group chats and specialized chat-like kinds (livechat, whatsapp, ...).
     * Neutral default: false; overridden by the discuss layer.
     *
     * @returns {boolean}
     */
    get isDirectChat() {
        return false;
    }
    /** @type {boolean} */
    areAttachmentsLoaded = false;
    group_public_id = fields.One("res.groups");
    attachments = fields.Many("ir.attachment", {
        /**
         * @param {import("models").Attachment} a1
         * @param {import("models").Attachment} a2
         */
        sort: (a1, a2) => (a1.id < a2.id ? 1 : -1),
    });
    /**
     * Whether the current user may leave this thread (stop being a member).
     * Neutral default: document threads have no membership to leave. The
     * discuss layer overrides this per channel kind
     * (@see allowedToLeaveChannelTypes there).
     *
     * @returns {boolean}
     */
    get canLeave() {
        return false;
    }
    /**
     * Whether the current user may unpin this thread from their sidebar /
     * messaging menu. Neutral default: document threads are never pinned.
     *
     * @returns {boolean}
     */
    get canUnpin() {
        return false;
    }
    /** @type {boolean} */
    can_react = true;
    chat_window = fields.One("ChatWindow", {
        inverse: "thread",
    });
    close_chat_window = fields.Attr(undefined, {
        /** @this {import("models").Thread} */
        onUpdate() {
            if (this.close_chat_window) {
                this.close_chat_window = undefined;
                this.closeChatWindow({ force: true });
            }
        },
    });
    composer = fields.One("Composer", {
        compute: () => ({}),
        inverse: "thread",
        onDelete: (r) => r.delete(),
    });
    counter = 0;
    counter_bus_id = 0;
    /** @type {string} */
    description;
    /** @type {string} */
    display_name;
    displayToSelf = fields.Attr(false, {
        compute() {
            return this.computeDisplayToSelf();
        },
        onUpdate() {
            this.onPinStateUpdated();
        },
    });
    /**
     * Compute of the `displayToSelf` field: whether this thread belongs in
     * the current user's sidebar / thread lists. Neutral default: document
     * threads are never listed; the discuss layer overrides this based on
     * membership and pin state.
     *
     * @returns {boolean}
     */
    computeDisplayToSelf() {
        return false;
    }
    followers = fields.Many("mail.followers", {
        /** @this {import("models").Thread} */
        onAdd(r) {
            r.thread = this;
        },
        onDelete: (r) => r.delete(),
    });
    selfFollower = fields.One("mail.followers", {
        /** @this {import("models").Thread} */
        onAdd(r) {
            r.thread = this;
        },
        onDelete: (r) => r.delete(),
    });
    /** @type {integer|undefined} */
    followersCount;
    loadOlder = false;
    loadNewer = false;
    /**
     * Counter shown next to this thread in navigation UIs (sidebar,
     * messaging menu, tabs). Contract: return the number the current user
     * should act on for this thread; 0 hides the badge. Base behavior:
     * mailboxes expose their own counter, document threads expose the
     * needaction counter. Layers refine this (e.g. unread messages for chat
     * channels) and must fall back to `super.importantCounter`.
     *
     * @returns {number}
     */
    get importantCounter() {
        if (this.model === "mail.box") {
            return this.counter;
        }
        return this.message_needaction_counter;
    }
    isDisplayed = fields.Attr(false, {
        compute() {
            return this.computeIsDisplayed();
        },
        onUpdate() {
            this.isDisplayedOnUpdate();
        },
    });
    isDisplayedOnUpdate() {}

    get composerDisabled() {
        return false;
    }

    get isFocused() {
        return this.isFocusedCounter !== 0;
    }
    isFocusedByThread = fields.Attr(false, {
        onUpdate() {
            if (this.isFocusedByThread) {
                this.isFocusedCounter++;
            } else {
                this.isFocusedCounter--;
            }
        },
    });
    isFocusedCounter = fields.Attr(0, {
        onUpdate() {
            if (this.isFocusedCounter < 0) {
                this.isFocusedCounter = 0;
            }
        },
    });
    isLoadingAttachments = false;
    isLoadedDeferred = new Deferred();
    isLoaded = fields.Attr(false, {
        /** @this {import("models").Thread} */
        onUpdate() {
            if (this.isLoaded) {
                this.isLoadedDeferred.resolve();
            } else {
                const def = this.isLoadedDeferred;
                this.isLoadedDeferred = new Deferred();
                this.isLoadedDeferred.then(() => def.resolve());
            }
        },
    });
    /** @type {Boolean|undefined} */
    has_mail_thread;
    message_main_attachment_id = fields.One("ir.attachment");
    message_needaction_counter = 0;
    message_needaction_counter_bus_id = 0;
    messageInEdition = fields.One("mail.message", { inverse: "threadAsInEdition" });
    /**
     * Contains continuous sequence of messages to show in message list.
     * Messages are ordered from older to most recent.
     * There should not be any hole in this list: there can be unknown
     * messages before start and after end, but there should not be any
     * unknown in-between messages.
     *
     * Content should be fetched and inserted in a controlled way.
     */
    messages = fields.Many("mail.message");
    /**
     * Phantom messages is a snapshot of `messages` while the thread is being loaded.
     * In other words: when thread is not loaded or loading, phantom messages are the
     * messages before thread loading.
     */
    phantomMessages = fields.Many("mail.message");
    /** @type {string} */
    modelName;
    /** @type {string} */
    module_icon;
    /**
     * Contains messages received from the bus that are not yet inserted in
     * `messages` list. This is a temporary storage to ensure nothing is lost
     * when fetching newer messages.
     */
    pendingNewMessages = fields.Many("mail.message");
    needactionMessages = fields.Many("mail.message", {
        inverse: "threadAsNeedaction",
        sort: (message1, message2) => message1.id - message2.id,
    });
    // FIXME: should be in the portal/frontend bundle but live chat can be loaded
    // before portal resulting in the field not being properly initialized.
    portal_partner = fields.One("res.partner");
    status = "new";
    /**
     * Stored scoll position of thread from top in ASC order.
     *
     * @type {number|'bottom'}
     */
    scrollTop = "bottom";
    transientMessages = fields.Many("mail.message");
    /* The additional recipients are the recipients that are manually added
     * by the user by using the "To" field of the Chatter. */
    additionalRecipients = fields.Attr([]);
    /* The suggested recipients are the recipients that are suggested by the
     * current model and includes the recipients of the last message. (e.g: for
     * a crm lead, the model will suggest the customer associated to the lead). */
    suggestedRecipients = fields.Attr([]);
    /** @type {String[]|undefined} */
    partner_fields;
    /** @type {String|undefined} */
    primary_email_field;
    hasLoadingFailed = false;
    /** @type {Error} */
    hasLoadingFailedError;
    canPostOnReadonly;
    /** @type {Boolean} */
    is_editable;
    /** @type {Boolean} */
    isLocallyPinned = fields.Attr(false, {
        onUpdate() {
            this.onPinStateUpdated();
        },
    });
    /** @type {"not_fetched"|"pending"|"fetched"} */
    fetchMembersState = "not_fetched";
    /** @type {integer|null} */
    highlightMessage = fields.One("mail.message");
    /** @type {String|undefined} */
    access_token;
    /** @type {String|undefined} */
    hash;
    /**
     * Partner id for non channel threads
     *  @type {integer|undefined}
     */
    pid;

    get accessRestrictedToGroupText() {
        if (!this.group_public_id?.full_name) {
            return false;
        }
        return _t('Access restricted to group "%(groupFullName)s"', {
            groupFullName: this.group_public_id.full_name,
        });
    }

    get busChannel() {
        return `${this.model}_${this.id}`;
    }

    get followersFullyLoaded() {
        return (
            this.followersCount ===
            (this.selfFollower ? this.followers.length + 1 : this.followers.length)
        );
    }

    get attachmentsInWebClientView() {
        const attachments = this.attachments.filter(
            (attachment) =>
                (attachment.isPdf || attachment.isImage) && !attachment.uploading,
        );
        attachments.sort((a1, a2) => a2.id - a1.id);
        return attachments;
    }

    get isUnread() {
        return this.needactionMessages.length > 0;
    }

    /**
     * Whether audio/video calls can be started on this thread. Neutral
     * default: document threads have no call support; the discuss layer
     * overrides this per channel kind (@see typesAllowingCalls there).
     *
     * @returns {boolean}
     */
    get allowCalls() {
        return false;
    }

    get canPostMessage() {
        return this.hasWriteAccess || (this.hasReadAccess && this.canPostOnReadonly);
    }

    /**
     * Return the name of the given persona to display in the context of this
     * thread.
     *
     * @param {import("models").Persona} persona
     * @returns {string}
     */
    getPersonaName(persona) {
        return persona?.displayName || persona?.name;
    }

    /**
     * Whether the thread actions offer an attachments panel. Neutral
     * default: false (the chatter has its own attachment box).
     *
     * @returns {boolean}
     */
    get hasAttachmentPanel() {
        return false;
    }

    /**
     * Whether this thread reads as a person-to-person conversation (direct
     * or group chat) rather than a broadcast channel or a document trail.
     * Drives e.g. the "@" prefix and unread-oriented counters. Neutral
     * default: false; overridden by the discuss layer.
     *
     * @returns {boolean}
     */
    get isChatChannel() {
        return false;
    }

    /**
     * Whether the current user can give this thread a personal display name.
     * Neutral default: false; overridden by the discuss layer.
     *
     * @returns {boolean}
     */
    get supportsCustomChannelName() {
        return false;
    }

    get displayName() {
        return this.display_name;
    }

    computeIsDisplayed() {
        return this.store.ChatWindow.get({ thread: this })?.isOpen;
    }

    get avatarUrl() {
        return this.module_icon ?? this.store.DEFAULT_AVATAR;
    }

    /**
     * Whether this thread carries a user-editable description. Neutral
     * default: false; overridden by the discuss layer per channel kind.
     *
     * @returns {boolean}
     */
    get allowDescription() {
        return false;
    }

    /**
     * Display name prefixed with the parent thread's one when this thread is
     * nested (e.g. sub-channels). Neutral default: no nesting.
     *
     * @returns {string}
     */
    get fullNameWithParent() {
        return this.displayName;
    }

    get isTransient() {
        return !this.id || this.id < 0;
    }

    get lastEditableMessageOfSelf() {
        const editableMessagesBySelf = this.nonEmptyMessages.filter(
            (message) => message.isSelfAuthored && message.editable,
        );
        if (editableMessagesBySelf.length > 0) {
            return editableMessagesBySelf.at(-1);
        }
        return null;
    }

    get needactionCounter() {
        return this.message_needaction_counter;
    }

    newestMessage = fields.One("mail.message", {
        inverse: "threadAsNewest",
        compute() {
            return this.messages.at(-1);
        },
    });

    get newestPersistentMessage() {
        return this.messages.findLast((msg) => Number.isInteger(msg.id));
    }

    newestPersistentAllMessages = fields.Many("mail.message", {
        compute() {
            const allPersistentMessages = this.allMessages.filter((message) =>
                Number.isInteger(message.id),
            );
            allPersistentMessages.sort((m1, m2) => m2.id - m1.id);
            return allPersistentMessages;
        },
    });

    newestPersistentOfAllMessage = fields.One("mail.message", {
        compute() {
            return this.newestPersistentAllMessages[0];
        },
    });

    get oldestPersistentMessage() {
        return this.messages.find((msg) => Number.isInteger(msg.id));
    }

    onPinStateUpdated() {}

    /**
     * Public link inviting people to this thread, if the thread kind
     * supports invitations. Neutral default: none.
     *
     * @returns {string|undefined}
     */
    get invitationLink() {
        return undefined;
    }

    get isEmpty() {
        return this.messages.length === 0;
    }

    get nonEmptyMessages() {
        return this.messages.filter((message) => !message.isEmpty);
    }

    get persistentMessages() {
        return this.messages.filter(
            (message) => !message.is_transient && !message.isPending,
        );
    }

    get prefix() {
        return this.isChatChannel ? "@" : "#";
    }

    get rpcParams() {
        return {};
    }

    async checkReadAccess() {
        await this.store.Thread.getOrFetch(this, ["hasReadAccess"]);
        return this.hasReadAccess;
    }

    /**
     * Whether messages can be fetched for this thread right now. Document
     * threads need a persistent id (drafts / unsaved records have no trail);
     * mailboxes use string ids. Extended by the discuss layer.
     *
     * @returns {boolean}
     */
    get canFetchMessages() {
        return this.model === "mail.box" || Boolean(this.id);
    }

    /** @param {{after: Number, before: Number}} */
    async fetchMessages({ after, around, before } = {}) {
        this.status = "loading";
        if (!this.canFetchMessages) {
            this.isLoaded = true;
            return [];
        }
        let res;
        try {
            res = await this.fetchMessagesData({ after, around, before });
            this.hasLoadingFailedError = undefined;
            this.hasLoadingFailed = false;
        } catch (e) {
            this.hasLoadingFailed = true;
            this.hasLoadingFailedError = e;
            this.isLoaded = true;
            this.status = "ready";
            throw e;
        }
        this.store.insert(res.data);
        const msgs = this.store["mail.message"].insert(res.messages.reverse());
        this.isLoaded = true;
        this.status = "ready";
        return msgs;
    }

    /** @param {{after: Number, before: Number}} */
    async fetchMessagesData({ after, around, before } = {}) {
        // ordered messages received: newest to oldest
        return await rpc(this.getFetchRoute(), {
            ...this.getFetchParams(),
            fetch_params: {
                limit:
                    !around && around !== 0
                        ? this.store.FETCH_LIMIT
                        : this.store.FETCH_LIMIT * 2,
                after,
                around,
                before,
            },
        });
    }

    /** @param {"older"|"newer"} epoch */
    async fetchMoreMessages(epoch = "older") {
        if (
            this.status === "loading" ||
            (epoch === "older" && !this.loadOlder) ||
            (epoch === "newer" && !this.loadNewer)
        ) {
            return;
        }
        const before = epoch === "older" ? this.oldestPersistentMessage?.id : undefined;
        const after = epoch === "newer" ? this.newestPersistentMessage?.id : undefined;
        let fetched = [];
        try {
            fetched = await this.fetchMessages({ after, before });
        } catch {
            return;
        }
        if (
            (after !== undefined &&
                !this.messages.some((message) => message.id === after)) ||
            (before !== undefined &&
                !this.messages.some((message) => message.id === before))
        ) {
            // there might have been a jump to message during RPC fetch.
            // Abort feeding messages as to not put holes in message list.
            return;
        }
        const alreadyKnownMessages = new Set(this.messages.map(({ id }) => id));
        const messagesToAdd = fetched.filter(
            (message) => !alreadyKnownMessages.has(message.id),
        );
        if (epoch === "older") {
            this.messages.unshift(...messagesToAdd);
        } else {
            this.messages.push(...messagesToAdd);
        }
        if (fetched.length < this.store.FETCH_LIMIT) {
            if (epoch === "older") {
                this.loadOlder = false;
            } else if (epoch === "newer") {
                this.loadNewer = false;
                const missingMessages = this.pendingNewMessages.filter(
                    ({ id }) => !alreadyKnownMessages.has(id),
                );
                if (missingMessages.length > 0) {
                    this.messages.push(...missingMessages);
                    this.messages.sort((m1, m2) => m1.id - m2.id);
                }
            }
        }
        this._enrichMessagesWithTransient();
        this.pendingNewMessages = [];
    }

    /**
     * Get the effective persona performing actions on this thread.
     * Priority order: logged-in user, portal partner (token-authenticated), guest.
     *
     * @returns {import("models").Persona}
     */
    get effectiveSelf() {
        return this.store.self_partner || this.store.self_guest;
    }

    /**
     * Whether new messages reach this thread through bus pushes, so that an
     * already-loaded thread never needs an incremental refetch. Base
     * behavior: true for mailboxes; the discuss layer adds channels.
     *
     * @returns {boolean}
     */
    get busKeepsMessagesFresh() {
        return this.model === "mail.box";
    }

    async fetchNewMessages() {
        if (
            this.status === "loading" ||
            (this.isLoaded && this.busKeepsMessagesFresh)
        ) {
            return;
        }
        const after = this.isLoaded ? this.newestPersistentMessage?.id : undefined;
        let fetched = [];
        try {
            fetched = await this.fetchMessages({ after });
        } catch {
            return;
        }
        // feed messages
        // could have received a new message as notification during fetch
        // filter out already fetched (e.g. received as notification in the meantime)
        let startIndex;
        if (after === undefined) {
            startIndex = 0;
        } else {
            const afterIndex = this.messages.findIndex(
                (message) => message.id === after,
            );
            if (afterIndex === -1) {
                // there might have been a jump to message during RPC fetch.
                // Abort feeding messages as to not put holes in message list.
                return;
            } else {
                startIndex = afterIndex + 1;
            }
        }
        const alreadyKnownMessages = new Set(this.messages.map((m) => m.id));
        const filtered = fetched.filter(
            (message) =>
                !alreadyKnownMessages.has(message.id) &&
                (this.persistentMessages.length === 0 ||
                    message.id < this.oldestPersistentMessage.id ||
                    message.id > this.newestPersistentMessage.id),
        );
        this.messages.splice(startIndex, 0, ...filtered);
        if (
            after === undefined &&
            filtered.length > 0 &&
            alreadyKnownMessages.size > 0
        ) {
            // already-known messages (e.g. received from the bus before the
            // initial fetch) may be newer than some fetched ones: restore the
            // continuous ascending order invariant of `messages`.
            this.messages.sort((m1, m2) => m1.id - m2.id);
        }
        Object.assign(this, {
            loadOlder:
                after === undefined && fetched.length === this.store.FETCH_LIMIT
                    ? true
                    : after === undefined && fetched.length !== this.store.FETCH_LIMIT
                      ? false
                      : this.loadOlder,
        });
    }

    getFetchParams() {
        if (this.model === "mail.box") {
            return {};
        }
        return {
            thread_id: this.id,
            thread_model: this.model,
            ...this.rpcParams,
        };
    }

    getFetchRoute() {
        if (this.model === "mail.box" && this.id === "inbox") {
            return `/mail/inbox/messages`;
        }
        if (this.model === "mail.box" && this.id === "starred") {
            return `/mail/starred/messages`;
        }
        if (this.model === "mail.box" && this.id === "history") {
            return `/mail/history/messages`;
        }
        return this.fetchRouteChatter;
    }

    get fetchRouteChatter() {
        return "/mail/thread/messages";
    }

    _loadAroundSequential = useSequential();

    /**
     * Get ready to jump to a message in a thread. This method will fetch the
     * messages around the message to jump to if required, and update the thread
     * messages accordingly.
     *
     * Jumps are sequentialized: a jump requested while another one is loading
     * is executed afterwards (intermediate queued jumps are superseded by the
     * last one) instead of being silently dropped.
     *
     * @param {import("models").Message} [messageId] if not provided, load around newest message
     */
    async loadAround(messageId) {
        if (this.isLoaded && this.messages.some(({ id }) => id === messageId)) {
            return;
        }
        return this._loadAroundSequential(() => this._loadAround(messageId));
    }

    /** @param {number} [messageId] */
    async _loadAround(messageId) {
        if (this.isLoaded && this.messages.some(({ id }) => id === messageId)) {
            return; // an earlier queued jump already loaded around this message
        }
        this.isLoaded = false;
        this.scrollTop = undefined;
        try {
            this.phantomMessages = this.messages;
            this.messages = await this.fetchMessages({ around: messageId });
        } catch {
            // Not a silent swallow: fetchMessages() recorded the failure in
            // hasLoadingFailed/hasLoadingFailedError, which drive the
            // in-thread error banner and its retry button. Rethrowing would
            // surface the same failure a second time as an uncaught error in
            // the fire-and-forget component call sites.
            this.isLoaded = true;
            return;
        } finally {
            this.phantomMessages = [];
        }
        this.isLoaded = true;
        this.loadNewer = messageId !== undefined ? true : false;
        this.loadOlder = true;
        const limit =
            !messageId && messageId !== 0
                ? this.store.FETCH_LIMIT
                : this.store.FETCH_LIMIT * 2;
        if (this.messages.length < limit) {
            const olderMessagesCount = this.messages.filter(
                ({ id }) => id < messageId,
            ).length;
            const newerMessagesCount = this.messages.filter(
                ({ id }) => id > messageId,
            ).length;
            if (olderMessagesCount < limit / 2 - 1) {
                this.loadOlder = false;
            }
            if (newerMessagesCount < limit / 2) {
                this.loadNewer = false;
            }
        }
        this._enrichMessagesWithTransient();
    }

    async markAllMessagesAsRead() {
        // Optimistic UI update: immediately clear needaction messages so the
        // notification item disappears and the systray counter decreases
        // without waiting for the bus notification.
        const inbox = this.store.inbox; // absent outside the web bundles
        const inboxSnapshot = inbox && snapshotCounter(inbox, "counter");
        const needactionSnapshot = snapshotCounter(this, "message_needaction_counter");
        const messages = [...this.needactionMessages];
        let inboxApplied = 0;
        for (const message of messages) {
            message.needaction = false;
            if (inbox) {
                inbox.messages.delete(message);
                inboxApplied += applyCounterDelta(inbox, "counter", -1);
            }
        }
        this.message_needaction_counter = 0;
        try {
            await this.store.env.services.orm.silent.call(
                "mail.message",
                "mark_all_as_read",
                [
                    [
                        ["model", "=", this.model],
                        ["res_id", "=", this.id],
                    ],
                ],
            );
        } catch (e) {
            // Roll back the optimistic update (see Message.setDone): no
            // correcting bus notification arrives on failure, so the inbox and
            // counters would otherwise stay wrong until reload. Counters are
            // only rolled back when their bus id did not advance in the
            // meantime: a newer absolute bus snapshot must not be overwritten
            // by a stale local value. Fire-and-forget caller -> swallow rather
            // than raise an unhandled rejection.
            for (const message of messages) {
                message.needaction = true;
                if (inbox) {
                    inbox.messages.add(message);
                }
            }
            inboxSnapshot?.restoreDelta(-inboxApplied);
            needactionSnapshot.restore();
            console.warn("Failed to mark all messages as read", e);
        }
    }

    /**
     * @param {Object} [options] used in overrides
     */
    markAsRead(options) {
        const newestPersistentMessage = this.newestPersistentOfAllMessage;
        if (!newestPersistentMessage && !this.isLoaded) {
            this.isLoadedDeferred
                .then(() => new Promise(setTimeout))
                .then(() => this.markAsRead(options));
            return;
        }
        if (this.message_needaction_counter > 0) {
            this.markAllMessagesAsRead();
        }
    }

    /** @param {import("models").Message} message */
    onNewSelfMessage(message) {}

    /**
     * Open this thread in the UI.
     *
     * Composition contract: `open()` delegates, in order, to
     * - `openChatUI()` — chat surfaces (Discuss app, chat windows),
     *   implemented by the discuss layer for channel-kind threads;
     * - `openWebClientUI()` — web-client surfaces (mailboxes, record form
     *   views), implemented by the web layer.
     * The chat seam therefore always wins over the web-client seam,
     * regardless of bundle/patch load order. Patches must extend one of the
     * two seams rather than `open()` itself, unless they only add side
     * effects around `super.open()` or handle their own thread model.
     *
     * @param {Object} [options]
     * @return {boolean} true if the thread was opened, false otherwise
     */
    open(options) {
        return this.openChatUI(options) || this.openWebClientUI(options);
    }

    /**
     * Chat-surface seam of `open()` (@see open). Neutral default: not
     * handled.
     *
     * @param {Object} [options]
     * @returns {boolean} true if the thread was opened
     */
    openChatUI(options) {
        return false;
    }

    /**
     * Web-client seam of `open()` (@see open). Neutral default: not handled
     * (e.g. on public pages without the action service).
     *
     * @param {Object} [options]
     * @returns {boolean} true if the thread was opened
     */
    openWebClientUI(options) {
        return false;
    }

    /**
     * Open this thread inside the Discuss application when appropriate
     * (e.g. Discuss is active on a large screen). Returning false lets the
     * caller fall back to a chat window (@see openChatUI in the discuss
     * layer). Neutral default: not handled.
     *
     * @returns {boolean} true if the thread was opened
     */
    openChannel() {
        return false;
    }

    async openChatWindow({
        focus = false,
        fromMessagingMenu,
        bypassCompact,
        swapOpened,
    } = {}) {
        const thread = await this.store.Thread.getOrFetch(this);
        if (!thread) {
            return;
        }
        await this.store.chatHub.initPromise;
        const cw = this.store.ChatWindow.insert(
            assignDefined({ thread: this }, { fromMessagingMenu, bypassCompact }),
        );
        cw.open({ focus, swapOpened });
        return cw;
    }

    async closeChatWindow(options = {}) {
        await this.store.chatHub.initPromise;
        const chatWindow = this.store.ChatWindow.get({ thread: this });
        await chatWindow?.close({ notifyState: false, ...options });
    }

    /**
     * Rename this thread from user input (chat window / Discuss header
     * editing). Contract: persist the new name server-side when the thread
     * kind supports renaming, else ignore the request. Neutral default:
     * document threads have no rename endpoint — no-op.
     *
     * @param {string} name
     */
    async rename(name) {}

    addOrReplaceMessage(message, tmpMsg) {
        // The message from other personas (not self) should not replace the tmpMsg
        if (
            tmpMsg &&
            tmpMsg.in(this.messages) &&
            this.effectiveSelf.eq(message.author)
        ) {
            this.messages.splice(this.messages.indexOf(tmpMsg), 1, message);
            return;
        }
        this.messages.add(message);
    }

    /**
     * Whether `post()` inserts an optimistic pending message right away, so
     * that composers may fire-and-forget the post RPC
     * (@see makeOptimisticPendingMessage). Neutral default: false, document
     * threads wait for the server response.
     *
     * @returns {boolean}
     */
    get hasOptimisticPost() {
        return false;
    }

    /**
     * Build and insert the optimistic (client-side pending) message shown
     * while a post RPC is in flight, for thread kinds with optimistic
     * posting (@see hasOptimisticPost). Contract: return the inserted
     * pending message, or undefined when the thread kind does not support
     * optimistic posting (neutral default).
     *
     * @param {number} tmpId temporary client-side message id
     * @param {ReturnType<import("@odoo/owl").markup>} body
     * @param {Object} postData
     * @returns {Promise<import("models").Message|undefined>}
     */
    async makeOptimisticPendingMessage(tmpId, body, postData) {
        return undefined;
    }

    /**
     *  @param {ReturnType<import("@odoo/owl").markup>} body
     *  @param {Object} extraData
     */
    async post(body, postData = {}, extraData = {}) {
        postData.attachments = postData.attachments ? [...postData.attachments] : []; // to not lose them on composer clear
        const { parentId } = postData;
        const params = await this.store.getMessagePostParams({
            body,
            postData,
            thread: this,
        });
        Object.assign(params, extraData);
        const tmpId = this.store.getNextTemporaryId();
        params.context = { ...user.context, ...params.context, temporary_id: tmpId };
        if (parentId) {
            params.post_data.parent_id = parentId;
        }
        const tmpMsg = await this.makeOptimisticPendingMessage(tmpId, body, postData);
        if (tmpMsg) {
            this.messages.push(tmpMsg);
            this.onNewSelfMessage(tmpMsg);
        }
        const data = await this.store.doMessagePost(params, tmpMsg);
        if (!data) {
            return;
        }
        return this.processMessagePostResponse(data, tmpMsg);
    }

    /**
     * Handle the response of a `/mail/message/post` RPC: insert the resulting
     * data and replace the temporary message with the persistent one. Also
     * used when re-attempting a failed post (@see Message.postFailRedo).
     *
     * @param {Object} data response of `/mail/message/post`
     * @param {import("models").Message} [tmpMsg] the associated temporary message
     * @returns {import("models").Message}
     */
    processMessagePostResponse(data, tmpMsg) {
        this.store.insert(data.store_data);
        /** @type {import("models").Message} */
        const message = this.store["mail.message"].get(data.message_id);
        this.addOrReplaceMessage(message, tmpMsg);
        this.onNewSelfMessage(message);
        // Only delete the temporary message now that seen_message_id is updated
        // to avoid flickering.
        tmpMsg?.delete();
        if (message.hasLink && this.store.hasLinkPreviewFeature) {
            rpc("/mail/link_preview", { message_id: message.id }, { silent: true });
        }
        return message;
    }

    /** @param {number} index */
    async setMainAttachmentFromIndex(index) {
        this.message_main_attachment_id = this.attachmentsInWebClientView[index];
        await this.store.env.services.orm.call(
            "ir.attachment",
            "register_as_main_attachment",
            [this.message_main_attachment_id.id],
        );
    }

    /**
     * Following a load more or load around, listing of messages contains persistent messages.
     * Transient messages are missing, so this function puts known transient messages at the
     * right place in message list of thread.
     */
    _enrichMessagesWithTransient() {
        for (const message of this.transientMessages) {
            if (message.id < this.oldestPersistentMessage?.id && !this.loadOlder) {
                this.messages.unshift(message);
            } else if (message.id > this.newestPersistentMessage?.id && !this.loadNewer) {
                this.messages.push(message);
            } else {
                let afterIndex = this.messages.findIndex((msg) => msg.id > message.id);
                if (afterIndex === -1) {
                    afterIndex = this.messages.length;
                }
                this.messages.splice(afterIndex, 0, message);
            }
        }
    }

    /**
     * Python model name under which this record is keyed in Store payloads
     * (@see Record._getActualModelName). All document threads serialize as
     * "mail.thread"; the discuss layer maps channels to their own key.
     *
     * @returns {string}
     */
    _getActualModelName() {
        return "mail.thread";
    }

    /**
     * Compute of the `correspondent` field of channel-kind threads: the
     * single "other" member this conversation is with, when that makes sense
     * (1:1 or self chats). Contract: return a channel member (or undefined);
     * overrides may special-case per channel kind and should fall back to
     * `super.computeCorrespondent()`. Neutral default: document threads have
     * no correspondent.
     *
     * @returns {import("models").ChannelMember|undefined}
     */
    computeCorrespondent() {
        return undefined;
    }

    /**
     * Members whose "seen" state may be reflected by message seen
     * indicators. The purpose is to let layers exclude technical members
     * (e.g. bots) to avoid "wrong" seen indicators. Neutral default:
     * document threads have no members.
     *
     * @returns {import("models").ChannelMember[]}
     */
    get membersThatCanSeen() {
        return [];
    }

    /**
     * Whether UIs (chat window header, member lists) should decorate the
     * correspondent with their country flag. Neutral default: false; kinds
     * with anonymous visitors (livechat) turn this on.
     *
     * @returns {boolean}
     */
    get showCorrespondentCountry() {
        return false;
    }

    /**
     * Channel member whose online (im) status stands for this thread in
     * chat window headers. Neutral default: none; the discuss layer returns
     * the correspondent of 1:1 chats.
     *
     * @returns {import("models").ChannelMember|undefined}
     */
    get imStatusMember() {
        return undefined;
    }

    /**
     * Whether this thread is the 1:1 chat with the given persona. Neutral
     * default: document threads are not chats.
     *
     * @param {import("models").Persona} persona
     * @returns {boolean}
     */
    isChatWith(persona) {
        return false;
    }

    /**
     * Composer type forced when this thread is displayed in a chat window;
     * undefined lets the composer use its default ("message"). Neutral
     * default: document threads log notes from chat windows.
     *
     * @returns {string|undefined}
     */
    get chatWindowComposerType() {
        return "note";
    }

    /**
     * Placeholder of the composer input for this thread.
     *
     * @returns {string}
     */
    get composerPlaceholder() {
        return _t("Message %(thread name)s…", { "thread name": this.displayName });
    }

    /**
     * Title of an out-of-focus OS notification for `message` posted on this
     * thread. Neutral default: the author's name.
     *
     * @param {import("models").Message} message
     * @returns {string}
     */
    outOfFocusNotificationTitle(message) {
        return message.authorName;
    }

    /**
     * Whether the message list shows a "start of conversation" banner once
     * the oldest message is loaded. Neutral default: false; the discuss
     * layer enables it per channel kind.
     *
     * @returns {boolean}
     */
    get hasStartOfConversationBanner() {
        return false;
    }

    /**
     * Title of the "start of conversation" banner
     * (@see hasStartOfConversationBanner).
     *
     * @returns {string}
     */
    get conversationStartTitle() {
        return this.displayName;
    }

    /**
     * Subtitle of the "start of conversation" banner
     * (@see hasStartOfConversationBanner). Neutral default: none.
     *
     * @returns {string}
     */
    get conversationStartSubtitle() {
        return "";
    }

    /**
     * Message id of the persisted new-message separator for the current
     * user, when this thread tracks per-member read state. Neutral default:
     * undefined (no separator support).
     *
     * @returns {number|undefined}
     */
    get newMessageSeparatorId() {
        return undefined;
    }
}

Thread.register();
