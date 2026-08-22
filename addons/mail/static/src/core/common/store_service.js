/** @odoo-module native */
import "@mail/core/common/im_status_service";
import "./_models.js";

import { FETCH_DATA_DEBOUNCE_DELAY } from "@mail/core/common/constants";
import { fields, makeStore, Store as BaseStore } from "@mail/core/common/record";
import { attClassObjectToString, prettifyMessageText } from "@mail/utils/common/format";
import { compareDatetime } from "@mail/utils/common/misc";
import { reactive } from "@odoo/owl";
import { loader } from "@web/components/emoji_picker";
import { browser } from "@web/core/browser/browser";
import { isMobileOS } from "@web/core/browser/feature_detection";
import { colorScheme } from "@web/core/color_scheme";
import { ConnectionLostError, rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { makeModelLog } from "@web/core/utils/asset_log";
import { Deferred, Mutex } from "@web/core/utils/concurrency";
import { debounce } from "@web/core/utils/timing";
import { session } from "@web/session";

const log = makeModelLog("store");

/**
 * @typedef {{isSpecial: true, channel_types: string[], label: string, displayName: string, description: string}} SpecialMention
 */
export const pyToJsModels = {
    "discuss.channel": "Thread",
    "mixin.mail.thread": "Thread",
};

export const addFieldsByPyModel = {
    "discuss.channel": { model: "discuss.channel" },
};

export class Store extends BaseStore {
    _makeInsertContext() {
        return { pyModels: Object.values(pyToJsModels) };
    }
    /**
     * @param {{pyModels: string[]}} ctx
     * @param {string} pyOrJsModelName
     * @returns {string}
     */
    _insertModelName(ctx, pyOrJsModelName) {
        if (ctx.pyModels.includes(pyOrJsModelName)) {
            console.warn(
                `store.insert() should receive the python model name instead of “${pyOrJsModelName}”.`,
            );
        }
        return pyToJsModels[pyOrJsModelName] || pyOrJsModelName;
    }
    /**
     * @param {string} pyOrJsModelName
     * @returns {Object|undefined}
     */
    _insertExtraFields(pyOrJsModelName) {
        return addFieldsByPyModel[pyOrJsModelName];
    }

    FETCH_LIMIT = 30;
    DEFAULT_AVATAR = "/mail/static/src/img/smiley/avatar.jpg";
    isReady = new Deferred();
    self_partner = fields.One("res.partner");
    self_guest = fields.One("mail.guest");
    get self() {
        return this.self_partner || this.self_guest;
    }
    allChannels = fields.Many("Thread", {
        inverse: "storeAsAllChannels",
        /** @this {import("models").Store} */
        onUpdate() {
            const busService = this.store.env.services.bus_service;
            if (!busService.isActive && this.allChannels.some((t) => !t.isTransient)) {
                busService.start();
            }
        },
    });
    inPublicPage = false;
    odoobot = fields.One("res.partner");
    useMobileView = fields.Attr(undefined, {
        /** @this {import("models").Store} */
        compute() {
            return this.store.env.services.ui.isSmall || isMobileOS();
        },
    });
    /** @type {Object<number, import("models").ResUsers>} */
    users = {};
    /** @type {number} */
    internalUserGroupId;
    mt_comment = fields.One("mail.message.subtype");
    mt_note = fields.One("mail.message.subtype");
    /** @type {boolean} */
    hasMessageTranslationFeature;
    hasLinkPreviewFeature = true;
    chatHub = fields.One("ChatHub", { compute: () => ({}) });
    messagingMenu = fields.One("MessagingMenu", { compute: () => ({}) });
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

    /** @type {Map<string, Promise<import("models").Thread|undefined>>} */
    _threadFetchPromises = new Map();
    /** @type {Set<string>} */
    _threadFetchAttempted = new Set();
    /** @type {Set<number>} */
    deletedMessageIds = new Set();

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
        /** @this {import("models").Store} */
        compute() {
            return (
                browser.localStorage.getItem(
                    "mail.user_setting.push_notification_dismissed",
                ) === "true"
            );
        },
        /** @this {import("models").Store} */
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

    /** @type {Map<string, Mutex>} */
    messagePostMutexes = new Map();
    /** @type {Map<number, Promise<number|undefined>>} */
    _partnerIdByUserIdFetches = new Map();

    /**
     * @param {{env?: import("@web/env").OdooEnv}} [ctx]
     * @returns {boolean}
     */
    shouldSimulateDarkTheme(ctx) {
        return (
            (ctx?.env?.inDiscussCallView ||
                ctx?.env?.inCallInvitation ||
                ctx?.env?.isDiscussPipBanner ||
                ctx?.env?.inWelcomePage) &&
            this.isOdooWhiteTheme &&
            !ctx?.env?.inMeetingSideActions &&
            !ctx?.env?.inDiscussActionPanel
        );
    }

    /**
     * @param {{env?: import("@web/env").OdooEnv}} [ctx]
     * @returns {string}
     */
    discussDropdownMenuClass(ctx) {
        const simulateDarkTheme = this.shouldSimulateDarkTheme(ctx);
        return attClassObjectToString({
            "o-discuss-dropdownMenu d-flex flex-column border-secondary": true,
            "o-simulateDarkTheme": simulateDarkTheme,
            "bg-view": !simulateDarkTheme,
        });
    }

    standaloneInboxMessages = fields.Many("mail.message", {
        /** @this {import("models").Store} */
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
     * @param {Object} params
     * @param {import("models").Message} tmpMessage
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
                    // The optimistic message stays on screen with a retry
                    // attached, so the failure is not raised -- but it must
                    // still be traceable: returning undefined and saying
                    // nothing makes a failed post indistinguishable from a
                    // post that returned no data.
                    console.warn("Failed to post message, retry offered", err);
                    tmpMessage.postFailRedo = async () => {
                        tmpMessage.postFailRedo = undefined;
                        const thread = tmpMessage.thread;
                        thread.messages.delete(tmpMessage);
                        thread.messages.add(tmpMessage);
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
     * @param {boolean} [options.requestData=false]
     * @param {boolean} [options.readonly=true]
     * @param {boolean} [options.silent=true]
     * @returns {Promise<any>} what the server resolved this request with
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

    async initialize() {
        if (this._initializePromise) {
            // Not a no-op worth hiding: `im_livechat`'s
            // `livechat_service.persist()` calls this expecting a
            // re-initialisation, and inside a mounted WebClient it silently
            // gets the memoised promise instead.
            log("initialize:memoized");
            return this._initializePromise;
        }
        log("initialize:first-call");
        this._initializePromise = (async () => {
            try {
                await this.fetchStoreData("init_messaging");
            } catch (error) {
                if (!(error instanceof ConnectionLostError)) {
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
     * @param {string} name
     * @param {*} params
     * @returns {{ fetch: () => ReturnType<Store["fetchStoreData"]>, invalidate: () => void, status: "not_fetched"|"fetching"|"fetched" }}
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
        // The batch is the unit that reaches the server, and its ORDER is what
        // the mail/livechat suites' `verifySteps` assert on -- so log the route
        // and the ordered names together.  Reconstructing this by hand from
        // failing step diffs is what an embed-ordering investigation costs
        // without it.
        if (log.active()) {
            log(
                "fetchStoreData:batch",
                this.fetchReadonly ? "/mail/data" : "/mail/action",
                fetchParams.map(([name]) => name),
            );
        }
        this._fetchStoreDataRpc(
            fetchParams.map(([name, params, dataRequest]) => {
                if (dataRequest._autoResolve) {
                    if (params !== undefined) {
                        return [name, params];
                    } else {
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
                        continue;
                    }
                    if (insertError) {
                        dataRequest._resultDef.reject(insertError);
                    } else if (dataRequest._autoResolve) {
                        dataRequest._resolve = true;
                        continue;
                    } else {
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

    /**
     * @param {Object} fetchParams
     * @returns {Promise<Object>}
     */
    _fetchStoreDataRpc(fetchParams) {
        return rpc(
            this.fetchReadonly ? "/mail/data" : "/mail/action",
            { fetch_params: fetchParams, context: user.context },
            { silent: this.fetchSilent },
        );
    }

    /**
     * @param {string} tab
     * @returns Thread types matching the given tab.
     */
    setup() {
        super.setup();
        this._prevLastMessageId = null;
        this._temporaryIdOffset = 0.01;
        this._fetchStoreDataDebounced = debounce(
            this._fetchStoreDataDebounced,
            FETCH_DATA_DEBOUNCE_DELAY,
        );
    }

    onStarted() {
        this.isOdooWhiteTheme = !colorScheme.isDark || this.inPublicPage;
        /** @param {MessageEvent} ev */
        const onServiceWorkerMessage = (ev) => {
            const { data = {} } = ev;
            const { type, payload } = data;
            if (type === "notification-display-request") {
                const { correlationId, model, res_id } = payload;
                const thread = this.Thread.get({ model, id: res_id });
                let isTabFocused;
                try {
                    isTabFocused = parent.document.hasFocus();
                } catch {}
                const isInbox =
                    this.store.self_partner?.main_user_id?.notification_type ===
                        "inbox" && model !== "discuss.channel";
                if ((isTabFocused && thread?.isDisplayed) || isInbox) {
                    (
                        ev.source ?? browser.navigator.serviceWorker.controller
                    )?.postMessage({
                        type: "notification-display-response",
                        payload: { correlationId },
                    });
                }
            }
            if (type === "notification-displayed") {
                this.onPushNotificationDisplayed(payload);
            }
        };
        browser.navigator.serviceWorker?.addEventListener(
            "message",
            onServiceWorkerMessage,
        );
    }

    /** @param {{model: string, res_id: number}} payload */
    onPushNotificationDisplayed(payload) {
        if (["mixin.mail.thread", "discuss.channel"].includes(payload.model)) {
            this.env.services["mail.out_of_focus"]._playSound();
        }
    }

    /**
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

    /** @type {number} */
    lastKnownMessageId = 0;

    /** @returns {number} */
    getLastMessageId() {
        return this.lastKnownMessageId;
    }

    /** @param {string} recordName */
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
     * @param {Object} param0
     * @param {number} param0.userId
     * @param {number} param0.partnerId
     * @returns {Promise<import("models").ResPartner|undefined>}
     */
    async getPartner({ userId, partnerId }) {
        if (userId) {
            let user = this.users[userId];
            if (!user) {
                this.users[userId] = { id: userId };
                user = this.users[userId];
            }
            if (!user.partner_id) {
                // Two callers wanting the same user at once each saw an empty
                // cache and each issued the read. Share the in-flight one.
                let fetch = this._partnerIdByUserIdFetches.get(userId);
                if (!fetch) {
                    fetch = this.env.services.orm.silent
                        .read("res.users", [user.id], ["partner_id"], {
                            context: { active_test: false },
                        })
                        .then(([userData]) => userData?.partner_id[0])
                        .finally(() => this._partnerIdByUserIdFetches.delete(userId));
                    this._partnerIdByUserIdFetches.set(userId, fetch);
                }
                const partner_id = await fetch;
                if (partner_id) {
                    user.partner_id = partner_id;
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
                    {
                        context: { active_test: false },
                        order: "active desc, share asc, id asc",
                    },
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

    /**
     * @param {number} id
     * @param {boolean} [forceOpen=false]
     * @returns {Promise<import("models").Thread>}
     */
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

    /** @param {import("models").Persona|Object} person */
    async openChat(person) {
        const chat = await this.getChat(person);
        chat?.open({ focus: true });
    }

    /**
     * @param {Object} document
     * @param {number} document.id
     * @param {string} document.model
     */
    openDocument({ id, model }) {
        this.env.services.action.doAction({
            type: "ir.actions.act_window",
            res_model: model,
            views: [[false, "form"]],
            res_id: id,
        });
    }

    /**
     * @param {MouseEvent} ev
     * @param {number} id
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
        const { count, count_is_capped, data, messages } = await rpc(
            thread.getFetchRoute(),
            {
                ...thread.getFetchParams(),
                fetch_params: {
                    is_notification,
                    search_term: await prettifyMessageText(searchTerm),
                    before,
                },
            },
        );
        this.insert(data);
        return {
            count,
            countIsCapped: Boolean(count_is_capped),
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
        services.bus_service.addEventListener("BUS:RECONNECT", () => {
            store._threadFetchAttempted.clear();
        });
        store.self_guest ??= { id: -1 };
        store.settings ??= {};
        store.onStarted();
        return store;
    },
};

registry.category("services").add("mail.store", storeService);
