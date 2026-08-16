/** @odoo-module native */
import { partnerCompareRegistry } from "@mail/core/common/partner_compare";
import { cleanTerm } from "@mail/utils/common/format";
import { toRaw } from "@odoo/owl";
import { loadEmoji } from "@web/components/emoji_picker/emoji_picker";
import { registry } from "@web/core/registry";
import { fuzzyLookup } from "@web/core/utils/search";

/**
 * @param {(item: any) => string} cleanedKeyFn
 * @param {string} cleanedSearchTerm
 * @returns {(a: any, b: any) => number}
 */
function byPrefixThenAlphaThenId(cleanedKeyFn, cleanedSearchTerm) {
    return (a, b) => {
        const key1 = cleanedKeyFn(a);
        const key2 = cleanedKeyFn(b);
        const starts1 = key1.startsWith(cleanedSearchTerm);
        const starts2 = key2.startsWith(cleanedSearchTerm);
        if (starts1 !== starts2) {
            return starts1 ? -1 : 1;
        }
        if (key1 !== key2) {
            return key1 < key2 ? -1 : 1;
        }
        return a.id - b.id;
    };
}

/** @typedef {import("@web/components/emoji_picker/emoji_picker").Emoji} Emoji */
/** @typedef {import("@mail/core/common/suggestion_hook").Suggestion} Suggestion */
export class SuggestionService {
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {import("services").ServiceFactories} services
     */
    constructor(env, services) {
        this.env = env;
        this.orm = services.orm;
        this.store = services["mail.store"];
        this.composer = services["mail.composer"];
        this.emojis;
    }

    /**
     * @param {import('models').Thread} thread
     * @param {import("@web/env").OdooEnv} [env]
     * @returns {Array<[string, number?, number?]>}
     */
    getSupportedDelimiters(thread, env) {
        return [["@"], ["#"], ["::"], [":", undefined, 2]];
    }

    /**
     * @param {Object} search
     * @param {string} search.delimiter
     * @param {string} search.term
     * @param {Object} [options]
     * @param {import("models").Thread} [options.thread]
     * @param {AbortSignal} [options.abortSignal]
     */
    async fetchSuggestions({ delimiter, term }, { thread, abortSignal } = {}) {
        const cleanedSearchTerm = cleanTerm(term);
        switch (delimiter) {
            case "@":
                await this.fetchPartnersRoles(cleanedSearchTerm, thread, {
                    abortSignal,
                });
                break;
            case "#":
                await this.fetchThreads(cleanedSearchTerm, { abortSignal });
                break;
            case "::":
                await this.store.cannedResponses.fetch();
                break;
            case ":": {
                const { emojis } = await loadEmoji();
                this.emojis = emojis;
                break;
            }
        }
    }

    /**
     * @param {string} model
     * @param {string} method
     * @param {any[]} args
     * @param {Object} kwargs
     * @param {Object} [options={}]
     * @param {AbortSignal} [options.abortSignal]
     * @returns {Promise<any>}
     */
    makeOrmCall(model, method, args, kwargs, { abortSignal } = {}) {
        return new Promise((res, rej) => {
            /**
             * @type {Promise<any> & {abort?: () => void}}
             */
            const req = this.orm.silent.call(model, method, args, kwargs);
            const onAbort = () => {
                try {
                    req.abort();
                } catch (e) {
                    rej(e);
                }
            };
            abortSignal?.addEventListener("abort", onAbort);
            req.then(res)
                .catch(rej)
                .finally(() => abortSignal?.removeEventListener("abort", onAbort));
        });
    }
    /**
     * @param {string} term
     * @param {import("models").Thread} [thread]
     * @param {Object} [options]
     * @param {AbortSignal} [options.abortSignal]
     */
    async fetchPartnersRoles(term, thread, { abortSignal } = {}) {
        /** @type {{search: string, channel_id?: number}} */
        const kwargs = { search: term };
        if (thread?.isChannelKind) {
            kwargs.channel_id = thread.id;
        }
        const data = await this.makeOrmCall(
            "res.partner",
            thread?.isChannelKind
                ? "get_mention_suggestions_from_channel"
                : "get_mention_suggestions",
            [],
            kwargs,
            { abortSignal },
        );
        this.store.insert(data);
    }

    /**
     * @param {string} term
     * @param {Object} [options]
     * @param {AbortSignal} [options.abortSignal]
     */
    async fetchThreads(term, { abortSignal } = {}) {
        const data = await this.makeOrmCall(
            "discuss.channel",
            "get_mention_suggestions",
            [],
            { search: term },
            { abortSignal },
        );
        this.store.insert(data);
    }

    /**
     * @param {string} cleanedSearchTerm
     * @returns {{type: string, suggestions: Object[]}}
     */
    searchCannedResponseSuggestions(cleanedSearchTerm) {
        const cannedResponses = Object.values(
            this.store["mail.canned.response"].records,
        ).filter((cannedResponse) =>
            cleanTerm(cannedResponse.source).includes(cleanedSearchTerm),
        );
        return {
            type: "mail.canned.response",
            suggestions: cannedResponses.sort(
                byPrefixThenAlphaThenId(
                    /** @param {import("models").CannedResponse} c */
                    (c) => cleanTerm(c.source),
                    cleanedSearchTerm,
                ),
            ),
        };
    }

    /**
     * @param {string} cleanedSearchTerm
     * @returns {{type: string, suggestions: Emoji[]}}
     */
    searchEmojisSuggestions(cleanedSearchTerm) {
        /** @type {Emoji[]} */
        let emojis = [];
        if (this.emojis && cleanedSearchTerm) {
            emojis = fuzzyLookup(
                cleanedSearchTerm,
                this.emojis,
                /** @param {{shortcodes: string[]}} emoji */
                (emoji) => emoji.shortcodes,
            );
        }
        return {
            type: "emoji",
            suggestions: emojis,
        };
    }

    /**
     * @param {Object} param0
     * @param {string} [param0.delimiter]
     * @param {string} [param0.term]
     * @param {Object} [options={}]
     * @param {import("models").Thread} [options.thread]
     * @returns {{ type: string, suggestions: Suggestion[] }}
     */
    searchSuggestions({ delimiter, term }, { thread } = {}) {
        thread = toRaw(thread);
        const cleanedSearchTerm = cleanTerm(term);
        switch (delimiter) {
            case "@": {
                const partners = this.searchPartnerSuggestions(
                    cleanedSearchTerm,
                    thread,
                );
                const roles = this.searchRoleSuggestions(cleanedSearchTerm);
                return {
                    type: "Partner",
                    suggestions: [...partners.suggestions, ...roles.suggestions],
                };
            }
            case "#":
                return this.searchChannelSuggestions(cleanedSearchTerm);
            case "::":
                return this.searchCannedResponseSuggestions(cleanedSearchTerm);
            case ":":
                return this.searchEmojisSuggestions(cleanedSearchTerm);
        }
        return {
            type: undefined,
            suggestions: [],
        };
    }

    /**
     * @param {string} cleanedSearchTerm
     * @returns {{suggestions: Object[]}}
     */
    searchRoleSuggestions(cleanedSearchTerm) {
        const roles = Object.values(this.store["res.role"].records).filter((role) =>
            cleanTerm(role.name).includes(cleanedSearchTerm),
        );
        return {
            suggestions: roles.sort(
                byPrefixThenAlphaThenId(
                    /** @param {import("models").ResRole} r */
                    (r) => cleanTerm(r.name),
                    cleanedSearchTerm,
                ),
            ),
        };
    }

    /**
     * @param {import("models").ResPartner} partner
     * @param {import("models").Thread} [thread]
     * @returns {boolean}
     */
    isSuggestionValid(partner, thread) {
        return (
            (this.store.self_partner?.main_user_id?.share === false ||
                partner.mention_token) &&
            partner.notEq(this.store.odoobot)
        );
    }

    /**
     * @param {import("models").Thread} [thread]
     * @returns {import("models").ResPartner[]}
     */
    getPartnerSuggestions(thread) {
        return Object.values(this.store["res.partner"].records).filter((partner) =>
            this.isSuggestionValid(partner, thread),
        );
    }

    /**
     * @param {string} cleanedSearchTerm
     * @param {import("models").Thread} [thread]
     * @returns {{type: string, suggestions: Object[]}}
     */
    searchPartnerSuggestions(cleanedSearchTerm, thread) {
        const partners = this.getPartnerSuggestions(thread);
        const suggestions = [];
        for (const partner of partners) {
            if (!partner.name) {
                continue;
            }
            if (
                cleanTerm(partner.name).includes(cleanedSearchTerm) ||
                (partner.email && cleanTerm(partner.email).includes(cleanedSearchTerm))
            ) {
                suggestions.push(partner);
            }
        }
        suggestions.push(
            ...this.store.specialMentions.filter(
                (special) =>
                    thread &&
                    special.channel_types.includes(thread.channel_type) &&
                    cleanedSearchTerm.length >= Math.min(4, special.label.length) &&
                    (special.label.startsWith(cleanedSearchTerm) ||
                        cleanTerm(special.description.toString()).includes(
                            cleanedSearchTerm,
                        )),
            ),
        );
        return {
            type: "Partner",
            suggestions: [
                ...this.sortPartnerSuggestions(suggestions, cleanedSearchTerm, thread),
            ],
        };
    }

    /**
     * @param {(import("models").ResPartner|import("@mail/core/common/store_service").SpecialMention)[]} [partners]
     * @param {String} [searchTerm]
     * @param {import("models").Thread} thread
     * @returns {(import("models").ResPartner|import("@mail/core/common/store_service").SpecialMention)[]}
     */
    sortPartnerSuggestions(partners, searchTerm = "", thread = undefined) {
        const cleanedSearchTerm = cleanTerm(searchTerm);
        const compareFunctions = partnerCompareRegistry.getAll();
        const context = this.sortPartnerSuggestionsContext(thread);
        /** @type {(import("@mail/core/common/store_service").SpecialMention)[]} */
        const specials = [];
        /** @type {(import("models").ResPartner)[]} */
        const regular = [];
        for (const partner of partners) {
            ("isSpecial" in toRaw(partner) ? specials : regular).push(
                /** @type {any} */ (partner),
            );
        }
        regular.sort((p1, p2) => {
            p1 = toRaw(p1);
            p2 = toRaw(p2);
            for (const fn of compareFunctions) {
                const result = fn(p1, p2, {
                    env: this.env,
                    searchTerm: cleanedSearchTerm,
                    thread,
                    context,
                });
                if (result !== undefined) {
                    return result;
                }
            }
            return 0;
        });
        return [...specials, ...regular];
    }

    /** @param {import("models").Thread} [thread] */
    sortPartnerSuggestionsContext(thread) {
        return {};
    }

    /**
     * @param {string} cleanedSearchTerm
     * @returns {{type: string, suggestions: Object[]}}
     */
    searchChannelSuggestions(cleanedSearchTerm) {
        const suggestionList = Object.values(this.store.Thread.records).filter(
            (thread) =>
                thread.channel_type === "channel" &&
                thread.displayName &&
                cleanTerm(thread.displayName).includes(cleanedSearchTerm),
        );
        const byName = byPrefixThenAlphaThenId(
            /** @param {import("models").Thread} c */
            (c) => cleanTerm(c.displayName),
            cleanedSearchTerm,
        );
        /**
         * @param {import("models").Thread} c1
         * @param {import("models").Thread} c2
         * @returns {number}
         */
        const sortFunc = (c1, c2) => {
            const isPublicChannel1 =
                c1.channel_type === "channel" && !c1.group_public_id;
            const isPublicChannel2 =
                c2.channel_type === "channel" && !c2.group_public_id;
            if (isPublicChannel1 !== isPublicChannel2) {
                return isPublicChannel1 ? -1 : 1;
            }
            if (Boolean(c1.hasSelfAsMember) !== Boolean(c2.hasSelfAsMember)) {
                return c1.hasSelfAsMember ? -1 : 1;
            }
            return byName(c1, c2);
        };
        return {
            type: "Thread",
            suggestions: suggestionList.sort(sortFunc),
        };
    }
}

export const suggestionService = {
    dependencies: ["orm", "mail.store", "mail.composer"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {import("services").ServiceFactories} services
     */
    start(env, services) {
        return new SuggestionService(env, services);
    },
};

registry.category("services").add("mail.suggestion", suggestionService);
