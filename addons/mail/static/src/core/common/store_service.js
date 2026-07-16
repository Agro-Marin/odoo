/** @odoo-module native */
// Side-effect imports: the bundle graph must include every dependency
// referenced by ``mail.store`` through a runtime string identifier so
// that esbuild does not tree-shake them when ``store_service.js`` is
// pulled into a satellite bundle (e.g. ``web.assets_tests``) via mail
// tour files.
//
// - ``im_status_service``: declared in ``dependencies`` below; without
//   it service startup fails with "Missing dependencies: im_status".
// - ``./_models.js``: index of every Record subclass in ``core/common/``.
//   ``Store`` declares fields with string ``targetModel`` (e.g.
//   ``fields.One("res.partner")``); ``makeStore`` resolves those by
//   iterating ``modelRegistry`` and throws "No target model X exists"
//   if the corresponding ``*_model.js`` file was not imported.
import "@mail/core/common/im_status_service";
import "./_models.js";

import {
    fields,
    makeStore,
    Store as BaseStore,
    storeInsertFns,
} from "@mail/core/common/record";
import { threadCompareRegistry } from "@mail/core/common/thread_compare";
import {
    attClassObjectToString,
    cleanTerm,
    prettifyMessageText,
} from "@mail/utils/common/format";
import { compareDatetime } from "@mail/utils/common/misc";
import { reactive } from "@odoo/owl";
import { loader } from "@web/components/emoji_picker/emoji_picker";
import { browser } from "@web/core/browser/browser";
import { cookie } from "@web/core/browser/cookie";
import { isMobileOS } from "@web/core/browser/feature_detection";
import { _t } from "@web/core/l10n/translation";
import { ConnectionLostError, rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { Deferred, Mutex } from "@web/core/utils/concurrency";
import { patch } from "@web/core/utils/patch";
import { debounce } from "@web/core/utils/timing";
import { getOrigin } from "@web/core/utils/urls";
import { user } from "@web/services/user";
import { session } from "@web/session";

/**
 * @typedef {{isSpecial: boolean, channel_types: string[], label: string, displayName: string, description: string}} SpecialMention
 */

// "discuss.channel" literals: Store-payload ingestion mapping. Python keys
// thread data under its own model names; both are funneled into the single
// JS "Thread" model and channel payloads are tagged with their model so that
// `Thread.isChannelKind` (discuss layer) can discriminate. This is the one
// sanctioned place where base code spells out the channel model name.
export const pyToJsModels = {
    "discuss.channel": "Thread",
    "mail.thread": "Thread",
};

export const addFieldsByPyModel = {
    "discuss.channel": { model: "discuss.channel" },
};

patch(storeInsertFns, {
    makeContext(store) {
        if (!(store instanceof Store)) {
            return super.makeContext(...arguments);
        }
        return { pyModels: Object.values(pyToJsModels) };
    },
    getActualModelName(store, ctx, pyOrJsModelName) {
        if (!(store instanceof Store)) {
            return super.getActualModelName(...arguments);
        }
        if (ctx.pyModels.includes(pyOrJsModelName)) {
            console.warn(
                `store.insert() should receive the python model name instead of “${pyOrJsModelName}”.`,
            );
        }
        return pyToJsModels[pyOrJsModelName] || pyOrJsModelName;
    },
    getExtraFieldsFromModel(store, pyOrJsModelName) {
        if (!(store instanceof Store)) {
            return super.getExtraFieldsFromModel(...arguments);
        }
        return addFieldsByPyModel[pyOrJsModelName];
    },
});

export class Store extends BaseStore {
    static FETCH_DATA_DEBOUNCE_DELAY = 1;
    static OTHER_LONG_TYPING = 60000;
    static IM_STATUS_DEBOUNCE_DELAY = 1000;

    FETCH_LIMIT = 30;
    DEFAULT_AVATAR = "/mail/static/src/img/smiley/avatar.jpg";
    isReady = new Deferred();
    /** This is the current logged partner / guest */
    self_partner = fields.One("res.partner");
    self_guest = fields.One("mail.guest");
    get self() {
        return this.self_partner || this.self_guest;
    }
    allChannels = fields.Many("Thread", {
        inverse: "storeAsAllChannels",
        onUpdate() {
            const busService = this.store.env.services.bus_service;
            if (!busService.isActive && this.allChannels.some((t) => !t.isTransient)) {
                busService.start();
            }
        },
    });
    /**
     * Indicates whether the current user is using the application through the
     * public page.
     */
    inPublicPage = false;
    odoobot = fields.One("res.partner");
    useMobileView = fields.Attr(undefined, {
        compute() {
            return this.store.env.services.ui.isSmall || isMobileOS();
        },
    });
    users = {};
    /** @type {number} */
    internalUserGroupId;
    mt_comment = fields.One("mail.message.subtype");
    mt_note = fields.One("mail.message.subtype");
    /** @type {boolean} */
    hasMessageTranslationFeature;
    hasLinkPreviewFeature = true;
    // messaging menu
    menu = { counter: 0 };
    chatHub = fields.One("ChatHub", { compute: () => ({}) });
    failures = fields.Many("Failure", {
        /**
         * @param {import("models").Failure} f1
         * @param {import("models").Failure} f2
         */
        sort: (f1, f2) => (f2.lastMessage?.id ?? 0) - (f1.lastMessage?.id ?? 0),
    });
    settings = fields.One("Settings");
    emojiLoader = loader;

    /** @type {[[string, any, import("models").DataResponse]]} */
    fetchParams = [];
    fetchReadonly = true;
    fetchSilent = true;

    /**
     * In-flight `Thread.getOrFetch` requests, keyed by
     * `model,id,missingFieldNames`, so concurrent identical calls share one
     * promise. @see Thread.getOrFetch
     *
     * @type {Map<string, Promise<import("models").Thread|undefined>>}
     */
    _threadFetchPromises = new Map();
    /**
     * `model,id,fieldName` keys for which a `Thread.getOrFetch` response came
     * back without the requested field, to avoid refetching them forever.
     *
     * @type {Set<string>}
     */
    _threadFetchAttempted = new Set();

    cannedResponses = this.makeCachedFetchData("mail.canned.response");

    specialMentions = [
        {
            isSpecial: true,
            label: "everyone",
            channel_types: ["channel", "group"],
            displayName: "Everyone",
            description: _t("Notify everyone"),
        },
    ];

    isNotificationPermissionDismissed = fields.Attr(false, {
        compute() {
            return (
                browser.localStorage.getItem(
                    "mail.user_setting.push_notification_dismissed",
                ) === "true"
            );
        },
        /** @this {import("models").DiscussApp} */
        onUpdate() {
            if (this.isNotificationPermissionDismissed) {
                browser.localStorage.setItem(
                    "mail.user_setting.push_notification_dismissed",
                    "true",
                );
            } else {
                browser.localStorage.removeItem(
                    "mail.user_setting.push_notification_dismissed",
                );
            }
        },
    });

    /**
     * One mutex per thread so message posts on the same thread are ordered
     * without a slow post on one thread blocking posts on every other thread.
     * Entries are removed as soon as their mutex is idle.
     *
     * @type {Map<string, Mutex>}
     */
    messagePostMutexes = new Map();

    menuThreads = fields.Many("Thread", {
        /** @this {import("models").Store} */
        compute() {
            // `discuss` and `starred` only exist once the web/public_web
            // patches are applied: guard so portal/livechat bundles that load
            // core/common alone don't crash.
            /** @type {import("models").Thread[]} */
            const searchTerm = cleanTerm(this.discuss?.searchTerm ?? "");
            let threads = Object.values(this.Thread.records).filter(
                (thread) =>
                    (thread.displayToSelf ||
                        (thread.needactionMessages.length > 0 && !thread.isMailbox)) &&
                    cleanTerm(thread.displayName).includes(searchTerm),
            );
            const tab = this.discuss?.activeTab;
            if (tab === "inbox") {
                threads = threads.filter(({ channel_type }) =>
                    this.tabToThreadType("mailbox").includes(channel_type),
                );
            } else if (tab === "starred") {
                threads = this.starred ? [this.starred] : [];
            } else if (tab !== "notification") {
                threads = threads.filter(({ channel_type }) =>
                    this.tabToThreadType(tab).includes(channel_type),
                );
            }
            return threads;
        },
        /**
         * @this {import("models").Store}
         * @param {import("models").Thread} thread1
         * @param {import("models").Thread} thread2
         */
        sort(thread1, thread2) {
            const compareFunctions = threadCompareRegistry.getAll();
            for (const fn of compareFunctions) {
                const result = fn(thread1, thread2);
                if (result !== undefined) {
                    return result;
                }
            }
            return thread2.localId > thread1.localId ? 1 : -1;
        },
    });

    shouldSimulateDarkTheme(ctx) {
        return (
            (ctx?.env?.inDiscussCallView ||
                ctx?.env?.inCallInvitation ||
                ctx?.env.isDiscussPipBanner ||
                ctx?.env?.inWelcomePage) &&
            this.isOdooWhiteTheme &&
            !ctx?.env.inMeetingSideActions &&
            !ctx?.env.inDiscussActionPanel
        );
    }

    discussDropdownMenuClass(ctx) {
        const simulateDarkTheme = this.shouldSimulateDarkTheme(ctx);
        return attClassObjectToString({
            "o-discuss-dropdownMenu d-flex flex-column border-secondary": true,
            "o-simulateDarkTheme": simulateDarkTheme,
            "bg-view": !simulateDarkTheme,
        });
    }

    standaloneInboxMessages = fields.Many("mail.message", {
        compute() {
            const messages = (this.store.inbox?.messages ?? []).filter(
                (m) => !m.thread,
            );
            return messages.sort(
                (m1, m2) => compareDatetime(m2.datetime, m1.datetime) || m2.id - m1.id,
            );
        },
    });

    /**
     * @param {Object} params post message data
     * @param {import("models").Message} tmpMessage the associated temporary message
     */
    async doMessagePost(params, tmpMessage) {
        const mutexKey = `${params.thread_model},${params.thread_id}`;
        let mutex = this.messagePostMutexes.get(mutexKey);
        if (!mutex) {
            mutex = new Mutex();
            this.messagePostMutexes.set(mutexKey, mutex);
        }
        try {
            return await mutex.exec(async () => {
                let res;
                try {
                    res = await rpc("/mail/message/post", params, { silent: true });
                } catch (err) {
                    if (!tmpMessage) {
                        throw err;
                    }
                    tmpMessage.postFailRedo = async () => {
                        tmpMessage.postFailRedo = undefined;
                        const thread = tmpMessage.thread;
                        thread.messages.delete(tmpMessage);
                        thread.messages.add(tmpMessage);
                        // Route the redo through the regular post-response
                        // handling: the temporary message must be replaced by
                        // the persistent one even if the bus echo is lost
                        // (which is likely exactly when posts fail).
                        const data = await this.doMessagePost(params, tmpMessage);
                        if (data) {
                            thread.processMessagePostResponse(data, tmpMessage);
                        }
                    };
                }
                return res;
            });
        } finally {
            if (!mutex.locked && this.messagePostMutexes.get(mutexKey) === mutex) {
                this.messagePostMutexes.delete(mutexKey);
            }
        }
    }

    /**
     * @param {string} name
     * @param {any} params
     * @param {Object} [options={}]
     * @param {boolean} [options.requestData=false] when set to true, the return promise will
     *  resolve only when the requested data are returned (the data might come later, from another
     *  RPC or a bus notification for example). When set to false (the default), the return promise
     *  will resolve as soon as the RPC is done. This is intended to be true only for requests that
     *  will be resolved server side with `resolve_data_request`.
     * @param {boolean} [options.readonly=true] when set to false, the server will open a read-write
     *  cursor to process this request which is necessary if the request is expected to change data.
     * @param {boolean} [options.silent=true]
     * @returns {Deferred}
     */
    async fetchStoreData(
        name,
        params,
        { requestData = false, readonly = true, silent = true } = {},
    ) {
        const dataRequest = this.DataResponse.createRequest();
        dataRequest._autoResolve = !requestData;
        this.fetchParams.push([name, params, dataRequest]);
        this.fetchReadonly = this.fetchReadonly && readonly;
        this.fetchSilent = this.fetchSilent && silent;
        this._fetchStoreDataDebounced();
        return dataRequest._resultDef;
    }

    /**
     * Import data received from init_messaging.
     *
     * Idempotent: only the first call issues the RPC; subsequent calls
     * resolve against the same ``isReady`` Deferred.  The call site is
     * now the mount of the backend WebClient (or the explicit trigger
     * in the livechat embed) rather than ``start()``, so tests that
     * mount an isolated component (e.g. ``mountView`` for a form view)
     * do not incidentally hit ``/mail/data`` through the mail.store
     * service boot.
     */
    async initialize() {
        if (this._initializePromise) {
            return this._initializePromise;
        }
        this._initializePromise = (async () => {
            // ``init_messaging`` is idempotent and the only path that
            // populates ``store.isReady``.  Web-client bootstrap fires it
            // very early (WebClient.setup), so a transient network race
            // (server still warming after a fresh DB install, fetch
            // aborted by an early lifecycle event, intermittent 5xx) can
            // surface as a ``ConnectionLostError`` that:
            //   1. propagates as an unhandled rejection from this
            //      fire-and-forget call site, which the global error
            //      service logs as ``console.error`` — failing
            //      ``HttpCase`` tour tests that consider any browser
            //      error fatal (e.g. test_main_flows.TestUi.
            //      test_01_main_flow_tour was failing here in steady
            //      state); and
            //   2. leaves ``isReady`` unresolved forever, so chat /
            //      notification / discuss components hang on
            //      ``await store.isReady``.
            // A single retry covers the first-request-after-cold-boot
            // window without masking persistent connection loss — if
            // the second attempt also fails, the error propagates as
            // before and the user (or the test) sees the real problem.
            try {
                await this.fetchStoreData("init_messaging");
            } catch (error) {
                if (!(error instanceof ConnectionLostError)) {
                    // don't cache the failure: a later initialize() call must
                    // be able to retry instead of returning the stale
                    // rejection forever (isReady would then never resolve).
                    this._initializePromise = undefined;
                    throw error;
                }
                try {
                    await this.fetchStoreData("init_messaging");
                } catch (retryError) {
                    this._initializePromise = undefined;
                    throw retryError;
                }
            }
            this.isReady.resolve();
        })();
        return this._initializePromise;
    }

    /**
     * Create a cacheable version of the `fetchStoreData` method. The result of the
     * request is cached once acquired. In case of failure, the deferred is
     * rejected and the cache is reset allowing to retry the request when
     * calling the function again.
     *
     * `invalidate()` drops the cached result so the next `fetch()` call hits
     * the server again (useful when a bus notification makes the cached data
     * unreliable). Invalidating while a fetch is in flight marks that result
     * as stale once it lands, without rejecting pending callers.
     *
     * @param {string} name
     * @param {*} params Parameters to pass to the `fetchStoreData` method.
     * @returns {{
     *      fetch: () => ReturnType<Store["fetchStoreData"]>,
     *      invalidate: () => void,
     *      status: "not_fetched"|"fetching"|"fetched"
     * }}
     */
    makeCachedFetchData(name, params) {
        let def = null;
        let invalidatedWhileFetching = false;
        const r = reactive({
            status: "not_fetched",
            fetch: () => {
                if (["fetching", "fetched"].includes(r.status)) {
                    return def;
                }
                r.status = "fetching";
                invalidatedWhileFetching = false;
                def = new Deferred();
                const fetchDef = def;
                this.fetchStoreData(name, params).then(
                    (result) => {
                        if (fetchDef === def) {
                            r.status = invalidatedWhileFetching
                                ? "not_fetched"
                                : "fetched";
                        }
                        fetchDef.resolve(result);
                    },
                    (error) => {
                        if (fetchDef === def) {
                            r.status = "not_fetched";
                        }
                        fetchDef.reject(error);
                    },
                );
                return def;
            },
            invalidate: () => {
                if (r.status === "fetching") {
                    invalidatedWhileFetching = true;
                } else {
                    r.status = "not_fetched";
                }
            },
        });
        return r;
    }

    _fetchStoreDataDebounced() {
        const fetchParams = this.fetchParams;
        this._fetchStoreDataRpc(
            fetchParams.map(([name, params, dataRequest]) => {
                if (dataRequest._autoResolve) {
                    /**
                     * Auto-resolve requests don't need to pass any data request id as the server is
                     * expected to not return anything specific for them. It would work if id are
                     * given but it's more bytes on the network and more noise in the logs/tests.
                     */
                    if (params !== undefined) {
                        return [name, params];
                    } else {
                        // In a similar reasoning, also remove empty params.
                        return name;
                    }
                } else {
                    return [name, params, dataRequest.id];
                }
            }),
        ).then(
            (data) => {
                let insertError;
                try {
                    this.insert(data);
                } catch (error) {
                    insertError = error;
                }
                for (const [name, , dataRequest] of fetchParams) {
                    if (!dataRequest.exists()) {
                        // already resolved (and self-deleted) by a `_resolve`
                        // value in the inserted payload.
                        continue;
                    }
                    if (insertError) {
                        // One malformed record must not leave the whole batch
                        // pending forever: reject every request of the batch
                        // so awaiting callers (store.isReady, getOrFetch,
                        // joinChat, ...) fail fast instead of hanging.
                        dataRequest._resultDef.reject(insertError);
                    } else if (dataRequest._autoResolve) {
                        dataRequest._resolve = true;
                        continue; // `_resolve` onUpdate deletes the record
                    } else {
                        // The server response came back without resolving this
                        // request: resolve_data_request() was never called for
                        // it. Reject instead of pending forever.
                        dataRequest._resultDef.reject(
                            new Error(
                                `Data request "${name}" (id ${dataRequest.id}) was not resolved by the server response. The server route probably lacks a "resolve_data_request()" call.`,
                            ),
                        );
                    }
                    dataRequest.delete();
                }
                if (insertError) {
                    console.error("Failed to insert fetched mail data:", insertError);
                }
            },
            (error) => {
                for (const [, , dataRequest] of fetchParams) {
                    dataRequest._resultDef.reject(error);
                    if (dataRequest.exists()) {
                        dataRequest.delete();
                    }
                }
            },
        );
        this.fetchParams = [];
        this.fetchReadonly = true;
        this.fetchSilent = true;
    }

    _fetchStoreDataRpc(fetchParams) {
        return rpc(
            this.fetchReadonly ? "/mail/data" : "/mail/action",
            { fetch_params: fetchParams, context: user.context },
            { silent: this.fetchSilent },
        );
    }

    async startMeeting() {
        const thread = await this.createGroupChat({
            default_display_mode: "video_full_screen",
            partners_to: [this.self.id],
        });
        await this.store.chatHub.initPromise;
        this.ChatWindow.get(thread)?.update({ autofocus: 0 });
        await this.env.services["discuss.rtc"].toggleCall(thread, { camera: true });
        if (this.rtc.selfSession) {
            this.rtc.enterFullscreen({ autoOpenAction: "invite-people" });
        }
    }

    /**
     * @param {'chat' | 'group'} tab
     * @returns Thread types matching the given tab.
     */
    tabToThreadType(tab) {
        return tab === "chat" ? ["chat", "group"] : [tab];
    }

    handleClickOnLink(ev, thread) {
        const link = ev.target.closest("a");
        if (!link) {
            return;
        }
        const model = link.dataset.oeModel;
        const id = Number(link.dataset.oeId);
        if (link.classList.contains("o_channel_redirect") && model && id) {
            ev.preventDefault();
            this.Thread.getOrFetch({ model, id }).then((thread) => {
                if (thread) {
                    thread.open({ focus: true });
                } else {
                    this.env.services.notification.add(
                        _t("This thread is no longer available."),
                        {
                            type: "danger",
                        },
                    );
                }
            });
            return true;
        } else if (link.classList.contains("o_mail_redirect") && id) {
            ev.preventDefault();
            this.onClickPartnerMention(ev, id);
            return true;
        } else if (link.classList.contains("o_message_redirect")) {
            const message = this["mail.message"].get(id);
            const targetThread = message?.thread;
            const showAccessError = () =>
                this.env.services.notification.add(
                    _t("This conversation isn’t available."),
                    {
                        type: "danger",
                    },
                );
            if (targetThread) {
                targetThread.checkReadAccess().then((hasAccess) => {
                    if (hasAccess) {
                        targetThread.highlightMessage = message;
                        let isOpen = targetThread.eq(thread);
                        if (!isOpen) {
                            isOpen = targetThread.open({
                                focus: true,
                                swapOpened: false,
                            });
                        }
                        if (!isOpen) {
                            window.open(link.href);
                        }
                    } else {
                        if (this.self_partner) {
                            showAccessError();
                        } else {
                            window.open(link.href);
                        }
                    }
                });
                ev.preventDefault();
                return true;
            } else if (
                link.href &&
                new URL(link.href, getOrigin()).origin === getOrigin()
            ) {
                // link.href (not the raw attribute): a relative
                // /mail/message/... href is same-origin by definition but a
                // raw-attribute startsWith(origin) check never matched it,
                // navigating away instead of showing the access error
                showAccessError();
                ev.preventDefault();
                return true;
            }
        } else if (
            this.env.services.ui.isSmall &&
            ev.target.closest(".o-mail-ChatWindow") &&
            link.href &&
            !link.href.startsWith("#")
        ) {
            let url;
            try {
                url = new URL(link.href);
            } catch {
                // Ignore invalid URLs
                return false;
            }
            if (
                browser.location.host === url.host &&
                browser.location.pathname.startsWith("/odoo")
            ) {
                this.ChatWindow.get({ thread })?.fold();
            }
        }
        return false;
    }

    setup() {
        super.setup();
        // Per-store temporary-id state (previously module-level `let`s, which
        // were shared across every Store instance — e.g. a livechat embed and
        // the backend web client on the same page, or successive stores in the
        // test suite — causing temp-id collisions and cross-test state bleed).
        this._prevLastMessageId = null;
        this._temporaryIdOffset = 0.01;
        this._fetchStoreDataDebounced = debounce(
            this._fetchStoreDataDebounced,
            Store.FETCH_DATA_DEBOUNCE_DELAY,
        );
    }

    /** Provides an override point for when the store service has started. */
    onStarted() {
        this.isOdooWhiteTheme =
            cookie.get("color_scheme") !== "dark" || this.inPublicPage;
        navigator.serviceWorker?.addEventListener("message", (ev) => {
            const { data = {} } = ev;
            const { type, payload } = data;
            if (type === "notification-display-request") {
                const { correlationId, model, res_id } = payload;
                const thread = this.Thread.get({ model, id: res_id });
                let isTabFocused;
                try {
                    isTabFocused = parent.document.hasFocus();
                } catch {
                    // assumes tab not focused: parent.document from iframe triggers CORS error
                }
                // Prevent duplicate inbox push notifications since they're already handled by
                // `mail.message/inbox` bus notifications, and the `modelsHandleByPush` heuristic
                // in `out_of_focus_service.js` isn't reliable enough to detect these cases.
                // "discuss.channel" literal: `model` comes from the service
                // worker push payload; the corresponding Thread record may
                // not be loaded, so no record predicate can stand in.
                const isInbox =
                    this.store.self.main_user_id?.notification_type === "inbox" &&
                    model !== "discuss.channel";
                if ((isTabFocused && thread?.isDisplayed) || isInbox) {
                    // Reply through the worker that sent the request (ev.source)
                    // so the response is delivered even when this page is not
                    // yet controlled (controller is null until the worker claims
                    // it); fall back to the controller if source is unavailable.
                    (ev.source ?? navigator.serviceWorker.controller)?.postMessage({
                        type: "notification-display-response",
                        payload: { correlationId },
                    });
                }
            }
            if (type === "notification-displayed") {
                this.onPushNotificationDisplayed(payload);
            }
        });
    }

    onPushNotificationDisplayed(payload) {
        // Model names are push-payload values (@see notification-display-request
        // handler above), not Thread-record conditionals.
        if (["mail.thread", "discuss.channel"].includes(payload.model)) {
            this.env.services["mail.out_of_focus"]._playSound();
        }
    }

    /**
     * Search and fetch for a partner with a given user or partner id.
     * @param {Object} param0
     * @param {number} param0.userId
     * @param {number} param0.partnerId
     * @returns {Promise<import("models").Thread | undefined>}
     */
    async getChat({ userId, partnerId }) {
        const partner = await this.getPartner({ userId, partnerId });
        if (!partner) {
            return;
        }
        let chat = partner.searchChat();
        if (!chat?.self_member_id?.is_pinned) {
            chat = await this.joinChat(partner.id);
        }
        if (!chat) {
            this.env.services.notification.add(
                _t("An unexpected error occurred during the creation of the chat."),
                { type: "warning" },
            );
            return;
        }
        return chat;
    }

    /**
     * Highest message id (including temporary fractional ids) ever inserted in
     * this store. Tracked incrementally at message insert (see
     * `Message.update()`): scanning all message records on every post does not
     * scale. Monotonic: deleting the highest message does not lower it, which
     * is fine for its only purpose of generating increasing temporary ids.
     *
     * @type {number}
     */
    lastKnownMessageId = 0;

    /** @returns {number} */
    getLastMessageId() {
        return this.lastKnownMessageId;
    }

    notifySendFromMailbox(recordName) {
        this.env.services.notification.add(_t('Message posted on "%s"', recordName), {
            type: "info",
        });
    }

    getNextTemporaryId() {
        const lastMessageId = this.getLastMessageId();
        if (this._prevLastMessageId === lastMessageId) {
            this._temporaryIdOffset += 0.01;
        } else {
            this._prevLastMessageId = lastMessageId;
            this._temporaryIdOffset = 0.01;
        }
        return lastMessageId + this._temporaryIdOffset;
    }

    /**
     * Search and fetch for a partner with a given user or partner id.
     * @param {Object} param0
     * @param {number} param0.userId
     * @param {number} param0.partnerId
     * @returns {Promise<import("models").Persona> | undefined}
     */
    async getPartner({ userId, partnerId }) {
        if (userId) {
            let user = this.users[userId];
            if (!user) {
                this.users[userId] = { id: userId };
                user = this.users[userId];
            }
            if (!user.partner_id) {
                const [userData] = await this.env.services.orm.silent.read(
                    "res.users",
                    [user.id],
                    ["partner_id"],
                    { context: { active_test: false } },
                );
                if (userData) {
                    user.partner_id = userData.partner_id[0];
                }
            }
            if (!user.partner_id) {
                this.env.services.notification.add(
                    _t("You can only chat with existing users."),
                    {
                        type: "warning",
                    },
                );
                return;
            }
            partnerId = user.partner_id;
        }
        if (partnerId) {
            const partner = this["res.partner"].insert({ id: partnerId });
            if (!partner.main_user_id) {
                const [userId] = await this.env.services.orm.silent.search(
                    "res.users",
                    [["partner_id", "=", partnerId]],
                    { context: { active_test: false } },
                );
                if (!userId) {
                    this.env.services.notification.add(
                        _t(
                            "You can only chat with partners that have a dedicated user.",
                        ),
                        { type: "info" },
                    );
                    return;
                }
                if (!partner.main_user_id) {
                    partner.main_user_id = userId;
                }
            }
            return partner;
        }
    }

    async joinChat(id, forceOpen = false) {
        const { channel } = await this.fetchStoreData(
            "/discuss/get_or_create_chat",
            { partners_to: [id] },
            { readonly: false, requestData: true },
        );
        if (forceOpen) {
            await channel.open({ focus: true });
        }
        return channel;
    }

    async openChat(person) {
        const chat = await this.getChat(person);
        chat?.open({ focus: true });
    }

    openDocument({ id, model }) {
        this.env.services.action.doAction({
            type: "ir.actions.act_window",
            res_model: model,
            views: [[false, "form"]],
            res_id: id,
        });
    }

    /**
     * @param {MouseEvent} ev - Click event triggering the popover.
     * @param {number} id - Partner Id of mentioned partner.
     */
    onClickPartnerMention(ev, id) {
        this.openChat({ partnerId: id });
    }

    /**
     * @param {string} searchTerm
     * @param {Thread} thread
     * @param {number} before
     * @param {true|false|undefined} is_notification
     */
    async searchMessagesInThread(searchTerm, thread, before, is_notification) {
        const { count, data, messages } = await rpc(thread.getFetchRoute(), {
            ...thread.getFetchParams(),
            fetch_params: {
                is_notification,
                search_term: await prettifyMessageText(searchTerm), // formatted like message_post
                before,
            },
        });
        this.insert(data);
        return {
            count,
            loadMore: messages.length === this.FETCH_LIMIT,
            messages: this["mail.message"].insert(messages),
        };
    }
}
Store.register();

export const storeService = {
    dependencies: ["bus_service", "im_status", "ui", "popover"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {import("services").ServiceFactories} services
     * @returns {import("models").Store}
     */
    start(env, services) {
        const store = makeStore(env);
        store.insert(session.storeData);
        // the negative fetch cache ("this thread field came back absent, do
        // not request it again") must not survive a reconnection: the miss
        // may have been transient (access granted since, partial serializer
        // under load) and an unexpirable cache makes recovery impossible
        // without a full page reload
        services.bus_service.addEventListener("BUS:RECONNECT", () => {
            store._threadFetchAttempted.clear();
        });
        /**
         * Add defaults for `self` and `settings` because in livechat there could be no user and no
         * guest yet (both undefined at init), but some parts of the code that loosely depend on
         * these values will still be executed immediately. Providing a dummy default is enough to
         * avoid crashes, the actual values being filled at livechat init when they are necessary.
         */
        store.self_guest ??= { id: -1 };
        store.settings ??= {};
        // ``initialize()`` (the ``/mail/data`` init_messaging RPC) is no
        // longer triggered eagerly from service ``start()``.  It now fires
        // from the WebClient patch (backend) or the livechat embed
        // service, so contexts that boot the mail.store service without
        // a user-facing mail surface (e.g. unit tests mounting an
        // isolated view) don't incidentally hit ``/mail/data``.  Any
        // component that needs init_messaging data MUST either await
        // ``store.isReady`` or call ``store.initialize()`` explicitly.
        store.onStarted();
        return store;
    },
};

registry.category("services").add("mail.store", storeService);
