/** @odoo-module native */
import { isContentEditable, isTextNode } from "@html_editor/utils/dom_info";
import { rightPos } from "@html_editor/utils/position";
import {
    generatePartnerMentionElement,
    generateRoleMentionElement,
    generateSpecialMentionElement,
    generateThreadMentionElement,
} from "@mail/utils/common/format";
import { status, useComponent, useEffect, useState } from "@odoo/owl";
import { ConnectionAbortedError } from "@web/core/network";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";

/**
 * @typedef {Object} Option
 * @property {string} [buttonClass]
 * @property {string} [classList]
 * @property {number} [group]
 * @property {string} [label]
 * @property {string} [optionTemplate]
 * @property {string} [title]
 * @property {boolean} [unselectable]
 * @property {import("models").ResRole} [role]
 * @property {import("models").ResPartner} [partner]
 * @property {import("models").Thread} [thread]
 * @property {import("models").CannedResponse} [cannedResponse]
 * @property {import("@web/components/emoji_picker").Emoji} [emoji]
 * @property {string} [help]
 * @property {string} [source]
 * @property {true} [isSpecial]
 * @property {string} [displayName]
 * @property {string} [description]
 * @property {string[]} [channel_types]
 */
/**
 * @typedef {Object} SuggestionSearch
 * @property {string|undefined} delimiter
 * @property {number|undefined} position
 * @property {string} term
 */
/**
 * @typedef {import("models").ResPartner | import("models").ResRole | import("models").Thread | import("models").CannedResponse | import("@web/components/emoji_picker").Emoji | (import("@mail/discuss/core/common/channel_commands").ChannelCommand & {name: string}) | import("@mail/core/common/store_service").SpecialMention} Suggestion
 */
export const DELAY_FETCH = 250;

export class UseSuggestion {
    /** @param {import("@mail/core/common/composer").Composer} comp */
    constructor(comp) {
        this.comp = comp;
        this.fetchSuggestions = useDebounced(
            this.fetchSuggestions.bind(this),
            DELAY_FETCH,
        );
        useEffect(
            () => {
                this.detect();
            },
            () => [
                this.composer.selection.start,
                this.composer.selection.end,
                this.composer.composerText,
                this.composer.composerHtml,
            ],
        );
        useEffect(
            () => {
                this.update();
                if (this.search.position === undefined || !this.search.delimiter) {
                    return;
                }
                if (!this.composer.store.self_partner) {
                    return;
                }
                if (
                    this.lastFetchedSearch?.count === 0 &&
                    this.isSearchMoreSpecificThanLastFetch
                ) {
                    return;
                }
                this.fetchSuggestions();
            },
            () => [this.search.delimiter, this.search.position, this.search.term],
        );
    }
    /** @type {import("@mail/core/common/composer").Composer} */
    comp;
    get composer() {
        return this.comp.props.composer;
    }
    suggestionService = useService("mail.suggestion");
    state = useState({
        items: undefined,
        isFetching: false,
    });
    /** @type {SuggestionSearch} */
    search = {
        delimiter: undefined,
        position: undefined,
        term: "",
    };
    /**
     * @type {(SuggestionSearch & {count: number})|null|undefined}
     */
    lastFetchedSearch;
    get isSearchMoreSpecificThanLastFetch() {
        return (
            this.lastFetchedSearch.delimiter === this.search.delimiter &&
            this.search.term.startsWith(this.lastFetchedSearch.term) &&
            this.lastFetchedSearch.position >= this.search.position
        );
    }
    clearRawMentions() {
        this.composer.mentionedChannels.length = 0;
        this.composer.mentionedPartners.length = 0;
        this.composer.mentionedRoles.length = 0;
    }
    clearCannedResponses() {
        this.composer.cannedResponses = [];
    }
    clearSearch() {
        Object.assign(this.search, {
            delimiter: undefined,
            position: undefined,
            term: "",
        });
        this.state.items = undefined;
    }
    detect() {
        let start = 0;
        let end;
        let text = "";
        if (this.comp.composerService.htmlEnabled) {
            const selection = this.comp.editor.shared.selection.getEditableSelection();
            if (
                !isTextNode(selection.startContainer) ||
                !isContentEditable(selection.startContainer) ||
                !selection.isCollapsed
            ) {
                this.clearSearch();
                return;
            }
            start = selection.startOffset;
            end = selection.endOffset;
            text = selection.anchorNode.textContent;
        } else {
            start = this.composer.selection.start;
            end = this.composer.selection.end;
            text = this.composer.composerText;
        }
        if (start !== end) {
            this.clearSearch();
            return;
        }
        const candidatePositions = [];
        let numberOfSpaces = 0;
        for (let index = start - 1; index >= 0; --index) {
            if (/\s/.test(text[index])) {
                numberOfSpaces++;
                if (numberOfSpaces === 2) {
                    break;
                }
            }
            candidatePositions.push(index);
        }
        if (this.search.position !== undefined && this.search.position < start) {
            candidatePositions.push(this.search.position);
        }
        const supportedDelimiters = this.suggestionService.getSupportedDelimiters(
            this.thread,
            this.comp.env,
        );
        for (const candidatePosition of candidatePositions) {
            if (candidatePosition < 0 || candidatePosition >= text.length) {
                continue;
            }

            const findAppropriateDelimiter = () => {
                let goodCandidate;
                for (const [
                    delimiter,
                    allowedPosition,
                    minCharCountAfter,
                ] of supportedDelimiters) {
                    if (
                        text.substring(candidatePosition).startsWith(delimiter) &&
                        (allowedPosition === undefined ||
                            allowedPosition === candidatePosition) &&
                        (minCharCountAfter === undefined ||
                            start - candidatePosition - delimiter.length + 1 >
                                minCharCountAfter) &&
                        (!goodCandidate || delimiter.length > goodCandidate.length)
                    ) {
                        goodCandidate = delimiter;
                    }
                }
                return goodCandidate;
            };

            const candidateDelimiter = findAppropriateDelimiter();
            if (!candidateDelimiter) {
                continue;
            }
            const charBeforeCandidate = text[candidatePosition - 1];
            if (charBeforeCandidate && !/\s/.test(charBeforeCandidate)) {
                continue;
            }
            Object.assign(this.search, {
                delimiter: candidateDelimiter,
                position: candidatePosition,
                term: text.substring(
                    candidatePosition + candidateDelimiter.length,
                    start,
                ),
            });
            return;
        }
        this.clearSearch();
    }
    get thread() {
        return this.composer.thread || this.composer.message?.thread;
    }
    /** @param {Option} option */
    insert(option) {
        let position = this.search.position + 1;
        if (
            [":", "::"].includes(this.search.delimiter) ||
            (this.comp.composerService.htmlEnabled && this.search.delimiter !== "/")
        ) {
            position = this.search.position;
        }
        if (this.comp.composerService.htmlEnabled) {
            const { startContainer, endContainer, endOffset } =
                this.comp.editor.shared.selection.getEditableSelection();
            this.comp.editor.shared.selection.setSelection({
                anchorNode: startContainer,
                anchorOffset: position,
                focusNode: endContainer,
                focusOffset: endOffset,
            });
        }
        if (option.partner) {
            this.composer.mentionedPartners.add({ id: option.partner.id });
        } else if (option.role) {
            this.composer.mentionedRoles.add(option.role);
        } else if (option.thread) {
            this.composer.mentionedChannels.add({
                model: "discuss.channel",
                id: option.thread.id,
            });
        } else if (option.cannedResponse) {
            this.composer.cannedResponses.push(option.cannedResponse);
        }
        if (this.comp.composerService.htmlEnabled) {
            const inlineElement = makeMentionFromOption(option, {
                thread: this.thread,
            });
            this.comp.editor.shared.dom.insert(inlineElement);
            const [anchorNode, anchorOffset] = rightPos(inlineElement);
            this.comp.editor.shared.selection.setSelection({
                anchorNode,
                anchorOffset,
            });
            this.comp.editor.shared.dom.insert("\u00A0");
            this.comp.editor.shared.history.addStep();
        } else {
            this.composer.composerText =
                this.composer.composerText.substring(0, position) +
                this.composer.composerText.substring(this.composer.selection.end);
            this.clearSearch();
            this.composer.insertText(`${option.label} `, position);
        }
    }
    update() {
        if (!this.search.delimiter) {
            return;
        }
        const { type, suggestions } = this.suggestionService.searchSuggestions(
            this.search,
            {
                thread: this.thread,
            },
        );
        if (!suggestions.length) {
            this.state.items = undefined;
            return;
        }
        const limit = 8;
        suggestions.length = Math.min(suggestions.length, limit);
        this.state.items = { type, suggestions };
    }

    async fetchSuggestions() {
        if (!this.thread || status(this.comp) === "destroyed") {
            return;
        }
        const fetchedSearch = { ...this.search };
        let resetFetchingState = true;
        try {
            this.abortController?.abort();
            this.abortController = new AbortController();
            this.state.isFetching = true;
            await this.suggestionService.fetchSuggestions(fetchedSearch, {
                thread: this.thread,
                abortSignal: this.abortController.signal,
            });
        } catch (e) {
            this.lastFetchedSearch = null;
            if (e instanceof ConnectionAbortedError) {
                resetFetchingState = false;
                return;
            }
            throw e;
        } finally {
            if (resetFetchingState) {
                this.state.isFetching = false;
            }
        }
        if (!this.thread || status(this.comp) === "destroyed") {
            return;
        }
        this.update();
        this.lastFetchedSearch = {
            ...fetchedSearch,
            count: this.suggestionService.searchSuggestions(fetchedSearch, {
                thread: this.thread,
            }).suggestions.length,
        };
        if (!this.state.items?.suggestions.length) {
            this.clearSearch();
        }
    }
}

export function useSuggestion() {
    return new UseSuggestion(useComponent());
}

/**
 * @param {string} type
 * @param {Suggestion[]} suggestions
 * @param {Object} [params]
 * @param {import("models").Thread} [params.thread]
 * @returns {{ optionTemplate?: string, options: Option[] }}
 */
export function mapSuggestionsToOptions(type, suggestions, { thread } = {}) {
    const classList = "o-mail-Composer-suggestion";
    switch (type) {
        case "Partner":
            return {
                optionTemplate: "mail.Composer.suggestionPartner",
                options:
                    /**
                     * @type {(import("models").ResPartner | import("models").ResRole | import("@mail/core/common/store_service").SpecialMention)[]}
                     */ (suggestions).map((suggestion) => {
                        if ("isSpecial" in suggestion) {
                            return {
                                ...suggestion,
                                group: 1,
                                optionTemplate: "mail.Composer.suggestionSpecial",
                                classList,
                            };
                        }
                        if (suggestion?.Model?.getName?.() === "res.role") {
                            return {
                                label: suggestion.name,
                                role: suggestion,
                                thread,
                                optionTemplate: "mail.Composer.suggestionRole",
                                classList,
                            };
                        }
                        return {
                            label:
                                thread?.getPersonaName(suggestion) ?? suggestion.name,
                            partner: suggestion,
                            thread,
                            classList,
                        };
                    }),
            };
        case "Thread":
            return {
                optionTemplate: "mail.Composer.suggestionThread",
                options: /** @type {(import("models").Thread)[]} */ (suggestions).map(
                    (suggestion) => ({
                        label: suggestion.fullNameWithParent,
                        thread: suggestion,
                        classList,
                    }),
                ),
            };
        case "ChannelCommand":
            return {
                optionTemplate: "mail.Composer.suggestionChannelCommand",
                options:
                    /** @type {(import("@mail/discuss/core/common/channel_commands").ChannelCommand & {name: string})[]} */ (
                        suggestions
                    ).map((suggestion) => ({
                        label: suggestion.name,
                        help: suggestion.help,
                        classList,
                    })),
            };
        case "mail.canned.response":
            return {
                optionTemplate: "mail.Composer.suggestionCannedResponse",
                options: /** @type {(import("models").CannedResponse)[]} */ (
                    suggestions
                ).map((suggestion) => ({
                    cannedResponse: suggestion,
                    label: suggestion.substitution,
                    source: suggestion.source,
                    title: suggestion.substitution,
                    classList,
                })),
            };
        case "emoji":
            return {
                optionTemplate: "mail.Composer.suggestionEmoji",
                options:
                    /** @type {(import("@web/components/emoji_picker").Emoji)[]} */ (
                        suggestions
                    ).map((suggestion) => ({
                        emoji: suggestion,
                        label: suggestion.codepoints,
                    })),
            };
        default:
            return { options: [] };
    }
}

/**
 * @param {Option} option
 * @param {Object} [params]
 * @param {import("models").Thread} [params.thread]
 */
export function makeMentionFromOption(option, { thread } = {}) {
    let inlineElement;
    if (option.partner) {
        inlineElement = generatePartnerMentionElement(option.partner, thread);
    } else if (option.isSpecial) {
        inlineElement = generateSpecialMentionElement(option.label);
    } else if (option.role) {
        inlineElement = generateRoleMentionElement(option.role);
    } else if (option.thread) {
        inlineElement = generateThreadMentionElement(option.thread);
    } else {
        inlineElement = document.createTextNode(option.label);
    }
    return inlineElement;
}
