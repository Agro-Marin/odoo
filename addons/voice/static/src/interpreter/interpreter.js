// @ts-check
/** @odoo-module native */

import { normalize } from "@web/core/l10n/utils";
import { _t } from "@web/core/translation";
import { spokenSimilarity, spokenWords } from "@web/core/utils/search";

import {
    BUTTON_VERBS,
    COMMAND_PHRASES,
    COMMAND_WORDS,
    CONNECTORS,
    DICTATE_VERBS,
    FALSE_WORDS,
    FILLER,
    FILLER_PHRASES,
    GROUP_BY_TRIGGERS,
    INTERVALS,
    MONTHS,
    NEGATIONS,
    NUMBER_WORDS,
    OPEN_VERBS,
    ORDINALS,
    RECORD_NOUNS,
    RELATIVE_DAYS,
    RELATIVE_PERIODS,
    SET_LINKS,
    SET_VERBS,
    TRUE_WORDS,
    VIEW_TRIGGERS,
    VIEW_WORDS,
} from "./lexicon.js";
import { parseSpokenNumber } from "./numbers.js";

/**
 * How much a proposal may change before the user sees it.
 * NAVIGATE and SEARCH run at once and can be undone; STAGE writes into the
 * record without saving; COMMIT waits for an explicit confirmation.
 */
export const RISK = Object.freeze({ NAVIGATE: 0, SEARCH: 1, STAGE: 2, COMMIT: 3 });

const MENU_THRESHOLD = 0.8;
const SPAN_THRESHOLD = 0.88;
const STRICT_THRESHOLD = 0.9;
const MAX_SPAN = 6;

/**
 * @typedef {{ kind: string, risk: number, description: string, [key: string]: any }} Proposal
 * @typedef {{
 *   text: string,
 *   proposals: Proposal[],
 *   candidates: Proposal[],
 *   blocked: Proposal | null,
 * }} Interpretation
 * @typedef {{ raw: string, norm: string, start: number }} Token
 * @typedef {import("./vocabulary.js").Vocabulary} Vocabulary
 * @typedef {import("./vocabulary.js").ViewTerms} ViewTerms
 */

/**
 * @param {string} text
 * @returns {Token[]}
 */
function tokenize(text) {
    const tokens = [...text.matchAll(/[\p{L}\p{N}]+/gu)].map((match) => ({
        raw: match[0],
        norm: normalize(match[0]),
        start: /** @type {number} */ (match.index),
    }));
    const words = tokens.map((token) => token.norm);
    const filler = new Set();
    for (let index = 0; index < words.length; index++) {
        const length = phraseAt(words, index, FILLER_PHRASES);
        for (let offset = 0; offset < length; offset++) {
            filler.add(index + offset);
        }
    }
    return tokens.filter(
        (token, index) => !filler.has(index) && !FILLER.has(token.norm),
    );
}

/** @param {string[]} words */
function content(words) {
    return words.filter((word) => !CONNECTORS.has(word));
}

/** @type {WeakMap<object, string[][]>} */
const PHRASE_WORDS = new WeakMap();

/**
 * @param {object} term
 * @param {string[]} phrases
 * @returns {string[][]}
 */
function phraseWords(term, phrases) {
    let words = PHRASE_WORDS.get(term);
    if (!words) {
        words = phrases
            .map((phrase) => {
                const all = spokenWords(phrase);
                const meaningful = content(all);
                return meaningful.length ? meaningful : all;
            })
            .filter((phrase) => phrase.length);
        PHRASE_WORDS.set(term, words);
    }
    return words;
}

/**
 * @param {string[]} heard
 * @param {object} term
 * @param {string[]} phrases
 */
function termScore(heard, term, phrases) {
    const meaningful = content(heard);
    const words = meaningful.length ? meaningful : heard;
    let score = 0;
    for (const phrase of phraseWords(term, phrases)) {
        score = Math.max(score, spokenSimilarity(words, phrase));
    }
    return score;
}

/**
 * @template T
 * @param {string[]} heard
 * @param {T[]} terms
 * @param {(term: T) => string[]} phrasesOf
 * @returns {{ term: T, score: number }[]} best first
 */
function rank(heard, terms, phrasesOf) {
    return terms
        .map((term) => ({
            term,
            score: termScore(heard, /** @type {object} */ (term), phrasesOf(term)),
        }))
        .filter((match) => match.score > 0)
        .sort((a, b) => b.score - a.score);
}

/**
 * The best term named by a span of words starting at `start`, any length.
 *
 * @template T
 * @param {string[]} words
 * @param {number} start
 * @param {T[]} terms
 * @param {(term: T) => string[]} phrasesOf
 * @param {number} threshold
 * @returns {{ term: T, score: number, length: number } | null}
 */
function spanAt(words, start, terms, phrasesOf, threshold) {
    if (!terms.length || CONNECTORS.has(words[start])) {
        return null;
    }
    /** @type {{ term: T, score: number, length: number } | null} */
    let best = null;
    const longest = Math.min(MAX_SPAN, words.length - start);
    for (let length = 1; length <= longest; length++) {
        const span = words.slice(start, start + length);
        if (CONNECTORS.has(span[span.length - 1])) {
            continue;
        }
        const [match] = rank(span, terms, phrasesOf);
        if (match && match.score >= threshold && (!best || match.score >= best.score)) {
            best = { term: match.term, score: match.score, length };
        }
    }
    return best;
}

/**
 * @param {string[]} words
 * @param {string[][]} phrases
 */
function saysOneOf(words, phrases) {
    const heard = content(words);
    return phrases.some((phrase) => {
        const expected = content(phrase);
        return (
            expected.length === heard.length &&
            spokenSimilarity(heard, expected) >= STRICT_THRESHOLD
        );
    });
}

/**
 * @param {string[]} words
 * @param {number} start
 * @param {string[][]} phrases
 * @returns {number} how many words the phrase took, 0 if none starts here
 */
function phraseAt(words, start, phrases) {
    for (const phrase of [...phrases].sort((a, b) => b.length - a.length)) {
        if (phrase.every((word, offset) => words[start + offset] === word)) {
            return phrase.length;
        }
    }
    return 0;
}

// ---------------------------------------------------------------------------
// proposals
// ---------------------------------------------------------------------------

/**
 * @param {import("./vocabulary.js").MenuTerm} term
 * @param {string} [then]
 * @returns {Proposal}
 */
export function openMenu(term, then) {
    const label = term.isApp ? term.label : `${term.label} (${term.appLabel})`;
    return {
        kind: "open_menu",
        risk: RISK.NAVIGATE,
        description: _t("Open %s", label),
        menu: term.menu,
        then: then || "",
    };
}

/**
 * @param {string} kind
 * @param {ViewTerms | null} view
 * @returns {Proposal | null}
 */
export function sentenceCommand(kind, view) {
    const multiRecord = view && view.viewType !== "form";
    switch (kind) {
        case "help":
            return { kind, risk: RISK.NAVIGATE, description: _t("What can I say?") };
        case "open_home":
            return { kind, risk: RISK.NAVIGATE, description: _t("Home") };
        case "back":
            return view ? { kind, risk: RISK.NAVIGATE, description: _t("Back") } : null;
        case "next":
        case "previous":
            return view
                ? {
                      kind: "pager",
                      direction: kind,
                      risk: RISK.NAVIGATE,
                      description: kind === "next" ? _t("Next") : _t("Previous"),
                  }
                : null;
        case "new_record":
            return view ? { kind, risk: RISK.NAVIGATE, description: _t("New") } : null;
        case "save":
            return view ? { kind, risk: RISK.STAGE, description: _t("Save") } : null;
        case "discard":
            return view
                ? { kind, risk: RISK.STAGE, description: _t("Discard changes") }
                : null;
        case "undo":
            return { kind, risk: RISK.NAVIGATE, description: _t("Undo") };
        case "show_numbers":
            return { kind, risk: RISK.NAVIGATE, description: _t("Show numbers") };
        case "hide_numbers":
            return { kind, risk: RISK.NAVIGATE, description: _t("Hide numbers") };
        case "clear_search":
            return multiRecord
                ? { kind, risk: RISK.SEARCH, description: _t("Clear the search") }
                : null;
    }
    return null;
}

/**
 * @param {string[]} words
 * @param {ViewTerms | null} view
 * @returns {Proposal | null}
 */
function switchView(words, view) {
    if (!view || !words.some((word) => VIEW_TRIGGERS.has(word))) {
        return null;
    }
    const heard = content(words).filter((word) => !VIEW_TRIGGERS.has(word));
    if (heard.length !== 1 && !(heard.length === 2 && heard[0] === "tabla")) {
        return null;
    }
    const viewType = /** @type {Record<string, string>} */ (VIEW_WORDS)[
        heard[heard.length - 1]
    ];
    if (!viewType || !view.viewTypes.includes(viewType) || viewType === view.viewType) {
        return null;
    }
    return switchViewProposal(viewType);
}

/**
 * @param {string} viewType
 * @returns {Proposal}
 */
export function switchViewProposal(viewType) {
    return {
        kind: "switch_view",
        risk: RISK.NAVIGATE,
        viewType,
        description: _t("Show the %s view", viewType),
    };
}

/**
 * @param {string[]} words
 * @param {Vocabulary} vocabulary
 * @param {number} threshold
 * @returns {{ best: import("./vocabulary.js").MenuTerm, tied: import("./vocabulary.js").MenuTerm[], score: number } | null}
 */
function findMenu(words, vocabulary, threshold) {
    const ranked = rank(words, vocabulary.menus, (term) => term.phrases);
    if (!ranked.length || ranked[0].score < threshold) {
        return null;
    }
    const top = ranked[0].score;
    const tied = ranked
        .filter((match) => top - match.score < 0.02)
        .map((match) => match.term);
    const best =
        tied.find((term) => term.isApp) ||
        tied.find((term) => term.inCurrentApp) ||
        tied[0];
    const ambiguous =
        !best.isApp &&
        !best.inCurrentApp &&
        new Set(tied.map((term) => term.appLabel)).size > 1;
    return { best, tied: ambiguous ? tied.slice(0, 6) : [], score: top };
}

/**
 * "abre facturas sin pagar": the longest start that names a menu opens it,
 * and what follows is said again to the view it opens.
 *
 * @param {Token[]} tokens after the verb
 * @param {string} text
 * @param {Vocabulary} vocabulary
 * @returns {Interpretation | null}
 */
function openSomething(tokens, text, vocabulary) {
    const words = tokens.map((token) => token.norm);
    while (words.length && CONNECTORS.has(words[0])) {
        words.shift();
        tokens = tokens.slice(1);
    }
    if (!words.length) {
        return null;
    }
    const view = vocabulary.view;
    const first = content(words);
    const ordinal =
        /** @type {Record<string, number>} */ (ORDINALS)[first[0]] ??
        parseSpokenNumber(first[0] || "");
    if (
        view &&
        view.viewType !== "form" &&
        ordinal &&
        Number.isInteger(ordinal) &&
        first.slice(1).every((word) => RECORD_NOUNS.has(word)) &&
        ordinal <= view.recordCount
    ) {
        return single(text, {
            kind: "open_record",
            risk: RISK.NAVIGATE,
            index: ordinal - 1,
            description: _t("Open record %s", ordinal),
        });
    }
    for (let length = words.length; length >= 1; length--) {
        const threshold = length === words.length ? MENU_THRESHOLD : SPAN_THRESHOLD;
        const found = findMenu(words.slice(0, length), vocabulary, threshold);
        if (!found) {
            continue;
        }
        const rest = length < tokens.length ? text.slice(tokens[length].start) : "";
        if (found.tied.length) {
            return {
                text,
                proposals: [],
                candidates: found.tied.map((term) => openMenu(term, rest)),
                blocked: null,
            };
        }
        return single(text, openMenu(found.best, rest));
    }
    return null;
}

/**
 * @param {string} text
 * @param {Proposal} proposal
 * @returns {Interpretation}
 */
function single(text, proposal) {
    return { text, proposals: [proposal], candidates: [], blocked: null };
}

// ---------------------------------------------------------------------------
// search
// ---------------------------------------------------------------------------

/**
 * @param {string[]} words
 * @param {number} index
 * @param {any} today
 * @returns {{ generatorId: string, length: number } | null}
 */
function periodAt(words, index, today) {
    for (const [phrase, generatorId] of RELATIVE_PERIODS) {
        if (phrase.every((word, offset) => words[index + offset] === word)) {
            return { generatorId, length: phrase.length };
        }
    }
    const month = /** @type {Record<string, number>} */ (MONTHS)[words[index]];
    if (month && today) {
        const offset = today.month - month;
        if (offset >= 0) {
            return { generatorId: offset ? `month-${offset}` : "month", length: 1 };
        }
    }
    return null;
}

/**
 * @param {string[]} words
 * @param {number} index
 * @returns {{ interval: string, length: number } | null}
 */
function intervalAt(words, index) {
    const byWord = ["por", "by", "per"].includes(words[index]) ? 1 : 0;
    const interval = /** @type {Record<string, string>} */ (INTERVALS)[
        words[index + byWord]
    ];
    return interval ? { interval, length: byWord + 1 } : null;
}

/**
 * Clauses in any order: filters by their label, periods ("del mes pasado"),
 * group-bys ("agrupado por vendedor por mes"), field searches ("cliente
 * Acme"). A sentence counts as a search only when little of it is left over.
 *
 * @param {Token[]} tokens
 * @param {string} text
 * @param {ViewTerms} view
 * @param {any} today
 * @returns {Proposal | null}
 */
function parseSearch(tokens, text, view, today) {
    const words = tokens.map((token) => token.norm);
    /** @type {{ filters: string[], dateFilters: any[], groupBys: any[], fieldSearches: any[] }} */
    const spec = { filters: [], dateFilters: [], groupBys: [], fieldSearches: [] };
    /** @type {string[]} */
    const labels = [];
    let leftover = 0;
    let grouping = false;
    const fieldPhrases = (/** @type {any} */ term) => [term.label];

    /** @param {number} index */
    const clauseStarts = (index) =>
        phraseAt(words, index, GROUP_BY_TRIGGERS) ||
        periodAt(words, index, today) ||
        spanAt(words, index, view.filters, fieldPhrases, STRICT_THRESHOLD) ||
        spanAt(words, index, view.searchFields, fieldPhrases, STRICT_THRESHOLD);

    let index = 0;
    while (index < words.length) {
        const word = words[index];
        if (
            CONNECTORS.has(word) ||
            (grouping && ["luego", "then", "por", "by"].includes(word))
        ) {
            index++;
            continue;
        }
        const trigger = phraseAt(words, index, GROUP_BY_TRIGGERS);
        if (trigger || grouping) {
            const start = index + trigger;
            let at = start;
            while (at < words.length && CONNECTORS.has(words[at])) {
                at++;
            }
            const group = spanAt(
                words,
                at,
                view.groupBys,
                fieldPhrases,
                SPAN_THRESHOLD,
            );
            if (group) {
                at += group.length;
                const interval = group.term.isDate ? intervalAt(words, at) : null;
                if (interval) {
                    at += interval.length;
                }
                spec.groupBys.push(
                    interval
                        ? {
                              fieldName: group.term.fieldName,
                              interval: interval.interval,
                          }
                        : group.term.fieldName,
                );
                labels.push(_t("Group by %s", group.term.label));
                grouping = true;
                index = at;
                continue;
            }
            grouping = false;
            if (trigger) {
                leftover += trigger;
                index = start;
                continue;
            }
        }
        const dateFilter = spanAt(
            words,
            index,
            view.dateFilters,
            fieldPhrases,
            SPAN_THRESHOLD,
        );
        let periodIndex = index;
        if (dateFilter) {
            periodIndex += dateFilter.length;
            while (periodIndex < words.length && CONNECTORS.has(words[periodIndex])) {
                periodIndex++;
            }
        }
        const period = periodAt(words, periodIndex, today);
        if (period) {
            const target = (
                dateFilter?.term ? [dateFilter.term] : view.dateFilters
            ).find((term) => term.generatorIds.includes(period.generatorId));
            if (target) {
                spec.dateFilters.push({
                    name: target.name,
                    generatorIds: [period.generatorId],
                });
                labels.push(
                    `${target.label}: ${words.slice(periodIndex, periodIndex + period.length).join(" ")}`,
                );
                index = periodIndex + period.length;
                continue;
            }
        }
        const filter = spanAt(words, index, view.filters, fieldPhrases, SPAN_THRESHOLD);
        if (filter) {
            spec.filters.push(filter.term.name);
            labels.push(filter.term.label);
            index += filter.length;
            continue;
        }
        const searchVerb = ["busca", "buscar", "buscame", "search", "find"].includes(
            word,
        );
        const field = searchVerb
            ? { term: view.searchFields[0], length: 1 }
            : spanAt(words, index, view.searchFields, fieldPhrases, STRICT_THRESHOLD);
        if (field?.term) {
            let end = index + field.length;
            if (searchVerb && ["for", "a"].includes(words[end])) {
                end++;
            }
            const valueStart = end;
            while (end < words.length && (end === valueStart || !clauseStarts(end))) {
                end++;
            }
            if (end > valueStart) {
                const from = tokens[valueStart].start;
                const to = end < tokens.length ? tokens[end].start : text.length;
                const value = text
                    .slice(from, to)
                    .trim()
                    .replace(/[\s,;.]+$/, "");
                spec.fieldSearches.push({ fieldName: field.term.fieldName, value });
                labels.push(`${field.term.label}: ${value}`);
                index = end;
                continue;
            }
        }
        leftover++;
        index++;
    }
    const said = content(words).length;
    if (!labels.length || leftover > Math.max(1, Math.floor(said / 3))) {
        return null;
    }
    return searchProposal(spec, labels);
}

/**
 * @param {Record<string, any[]>} spec
 * @param {string[]} labels
 * @returns {Proposal}
 */
export function searchProposal(spec, labels) {
    return {
        kind: "search",
        risk: RISK.SEARCH,
        spec,
        description: labels.join(" · "),
    };
}

// ---------------------------------------------------------------------------
// form
// ---------------------------------------------------------------------------

/**
 * @param {import("./vocabulary.js").FormFieldTerm} field
 * @param {string} valueText
 * @param {Token[]} valueTokens
 * @param {any} today
 * @returns {{ value?: any, query?: string } | null}
 */
function fieldValue(field, valueText, valueTokens, today) {
    const words = valueTokens.map((token) => token.norm);
    switch (field.type) {
        case "char":
        case "text":
        case "html":
            return { value: valueText };
        case "integer": {
            const number = parseSpokenNumber(valueText);
            return number !== null && Number.isInteger(number)
                ? { value: number }
                : null;
        }
        case "float":
        case "monetary": {
            const number = parseSpokenNumber(valueText);
            return number !== null ? { value: number } : null;
        }
        case "boolean":
            if (words.length === 1 && TRUE_WORDS.has(words[0])) {
                return { value: true };
            }
            if (
                words.length === 1 &&
                (FALSE_WORDS.has(words[0]) || words[0] === "no")
            ) {
                return { value: false };
            }
            return null;
        case "selection": {
            const options = (field.selection || []).map(([key, label]) => ({
                key,
                label,
            }));
            const [match] = rank(words, options, (option) => [option.label]);
            return match && match.score >= MENU_THRESHOLD
                ? { value: match.term.key }
                : null;
        }
        case "many2one":
            return { query: valueText };
        case "date":
        case "datetime": {
            const days = /** @type {Record<string, number>} */ (RELATIVE_DAYS)[
                words.join(" ")
            ];
            if (days === undefined || !today) {
                return null;
            }
            const day = today.plus({ days });
            return { value: field.type === "date" ? day.startOf("day") : day };
        }
    }
    return null;
}

/**
 * "cantidad cinco", "pon el cliente a Acme", "notas: llamar mañana".
 *
 * @param {Token[]} tokens
 * @param {string} text
 * @param {ViewTerms} view
 * @param {any} today
 * @returns {Proposal | null}
 */
function parseSetField(tokens, text, view, today) {
    const form = view.form;
    if (!form?.fields.length) {
        return null;
    }
    const words = tokens.map((token) => token.norm);
    let start = 0;
    const withVerb = SET_VERBS.has(words[0]);
    if (withVerb) {
        start++;
    }
    while (start < words.length && CONNECTORS.has(words[start])) {
        start++;
    }
    const found = spanAt(
        words,
        start,
        form.fields,
        (field) => [field.label],
        withVerb ? SPAN_THRESHOLD : STRICT_THRESHOLD,
    );
    if (!found) {
        return null;
    }
    let valueStart = start + found.length;
    for (let links = 0; links < 2 && SET_LINKS.has(words[valueStart]); links++) {
        valueStart++;
    }
    if (valueStart >= tokens.length) {
        return null;
    }
    const valueText = text.slice(tokens[valueStart].start).trim();
    return setFieldProposal(found.term, valueText, today, tokens.slice(valueStart));
}

/**
 * @param {import("./vocabulary.js").FormFieldTerm} field
 * @param {string} valueText
 * @param {any} today
 * @param {Token[]} [valueTokens]
 * @returns {Proposal | null} null when the field cannot hold what was said
 */
export function setFieldProposal(
    field,
    valueText,
    today,
    valueTokens = tokenize(valueText),
) {
    const parsed = fieldValue(field, valueText, valueTokens, today);
    if (!parsed) {
        return null;
    }
    return {
        kind: "set_field",
        risk: RISK.STAGE,
        fieldName: field.name,
        fieldType: field.type,
        relation: field.relation,
        ...parsed,
        description: _t("%(field)s: %(value)s", {
            field: field.label,
            value: parsed.query ?? String(parsed.value),
        }),
    };
}

/**
 * @param {string[]} words
 * @param {ViewTerms} view
 * @returns {Proposal | null}
 */
function parseButton(words, view) {
    const buttons = view.form?.buttons || [];
    if (!buttons.length) {
        return null;
    }
    const withVerb = words.some((word) => BUTTON_VERBS.has(word));
    const heard = words.filter(
        (word) =>
            !BUTTON_VERBS.has(word) &&
            !["clic", "click", "boton", "button"].includes(word),
    );
    const threshold = withVerb ? MENU_THRESHOLD : SPAN_THRESHOLD;
    for (let start = 0; start < heard.length; start++) {
        const found = spanAt(
            heard,
            start,
            buttons,
            (button) => [button.label],
            threshold,
        );
        if (!found) {
            continue;
        }
        const leftover = content([
            ...heard.slice(0, start),
            ...heard.slice(start + found.length),
        ]).filter((word) => !NEGATIONS.has(word));
        if (leftover.length > 2) {
            return null;
        }
        return buttonProposal(found.term, view.form?.displayName);
    }
    return null;
}

/**
 * @param {import("./vocabulary.js").ButtonTerm} button
 * @param {string} [recordName]
 * @returns {Proposal}
 */
export function buttonProposal(button, recordName) {
    return {
        kind: "click_button",
        risk: RISK.COMMIT,
        button,
        description: recordName
            ? _t("%(button)s on %(record)s", {
                  button: button.label,
                  record: recordName,
              })
            : button.label,
    };
}

const DICTATED_TYPES = ["char", "text", "html"];

/**
 * "dicta notas": what follows is spoken into that field until stopped.
 *
 * @param {string[]} words
 * @param {Vocabulary} vocabulary
 * @returns {Proposal | null}
 */
function parseDictate(words, vocabulary) {
    const fields = (vocabulary.view?.form?.fields || []).filter((field) =>
        DICTATED_TYPES.includes(field.type),
    );
    if (!vocabulary.canDictate || !fields.length || !DICTATE_VERBS.has(words[0])) {
        return null;
    }
    const heard = content(words.slice(1)).filter((word) => !DICTATE_VERBS.has(word));
    let field = fields.find((term) => term.type !== "char") || fields[0];
    if (heard.length) {
        const [match] = rank(heard, fields, (term) => [term.label]);
        field = match && match.score >= SPAN_THRESHOLD ? match.term : null;
    }
    if (!field) {
        return null;
    }
    return {
        kind: "dictate",
        risk: RISK.STAGE,
        fieldName: field.name,
        fieldType: field.type,
        description: _t("Dictating into %s", field.label),
    };
}

/**
 * @param {import("./vocabulary.js").TargetTerm} target
 * @param {number} index
 * @returns {Proposal}
 */
function clickTarget(target, index) {
    return {
        kind: "click_target",
        risk: target.risk,
        index,
        description: target.label
            ? _t("%(number)s: %(label)s", { number: index + 1, label: target.label })
            : String(index + 1),
    };
}

/**
 * "siete", "número siete", "clic en 7" while the numbers are shown.
 *
 * @param {string[]} words
 * @param {Vocabulary} vocabulary
 * @returns {Proposal | null}
 */
function parseNumber(words, vocabulary) {
    const targets = vocabulary.targets || [];
    if (!vocabulary.numbersShown || !targets.length) {
        return null;
    }
    const heard = content(words).filter(
        (word) =>
            !NUMBER_WORDS.has(word) && !BUTTON_VERBS.has(word) && !NEGATIONS.has(word),
    );
    const number = parseSpokenNumber(heard.join(" "));
    if (
        number === null ||
        !Number.isInteger(number) ||
        number < 1 ||
        number > targets.length
    ) {
        return null;
    }
    return clickTarget(targets[number - 1], number - 1);
}

/**
 * "haz clic en Filtros": whatever is on screen, by the label it shows.
 *
 * @param {string[]} words
 * @param {Vocabulary} vocabulary
 * @returns {Proposal | null}
 */
function parseClickLabel(words, vocabulary) {
    const targets = (vocabulary.targets || []).map((target, index) => ({
        ...target,
        index,
    }));
    if (!targets.length || !words.some((word) => BUTTON_VERBS.has(word))) {
        return null;
    }
    const heard = words.filter(
        (word) => !BUTTON_VERBS.has(word) && !["clic", "click"].includes(word),
    );
    const [match] = rank(
        heard,
        targets.filter((target) => target.label),
        (target) => [target.label],
    );
    if (!match || match.score < SPAN_THRESHOLD) {
        return null;
    }
    return clickTarget(match.term, match.term.index);
}

/**
 * @param {string[]} words
 * @param {Vocabulary} vocabulary
 * @returns {Proposal | null}
 */
function parseCommand(words, vocabulary) {
    const named = COMMAND_WORDS.has(words[0]);
    const heard = named ? words.slice(1) : words;
    const [match] = rank(heard, vocabulary.commands, (command) => [command.name]);
    if (!match || match.score < (named ? MENU_THRESHOLD : STRICT_THRESHOLD)) {
        return null;
    }
    return commandProposal(match.term);
}

/**
 * @param {import("./vocabulary.js").CommandTerm} command
 * @returns {Proposal}
 */
export function commandProposal(command) {
    return {
        kind: "run_command",
        risk: command.category === "view_switcher" ? RISK.NAVIGATE : RISK.COMMIT,
        command,
        description: command.name,
    };
}

// ---------------------------------------------------------------------------

/**
 * @param {Interpretation} interpretation
 * @param {boolean} negated
 * @returns {Interpretation}
 */
export function guardNegation(interpretation, negated) {
    if (!negated) {
        return interpretation;
    }
    const blocked = [...interpretation.proposals, ...interpretation.candidates].find(
        (proposal) => proposal.risk === RISK.COMMIT,
    );
    if (!blocked) {
        return interpretation;
    }
    return { text: interpretation.text, proposals: [], candidates: [], blocked };
}

/** @param {string} text */
export function isNegated(text) {
    return tokenize(text).some((token) => NEGATIONS.has(token.norm));
}

/**
 * What a sentence asks of the view in front of the user, as proposals: the
 * interpreter decides nothing is run, the caller does, by risk.
 *
 * @param {string} text
 * @param {Vocabulary} vocabulary
 * @returns {Interpretation}
 */
export function interpret(text, vocabulary) {
    const tokens = tokenize(text);
    const words = tokens.map((token) => token.norm);
    /** @type {Interpretation} */
    const nothing = { text, proposals: [], candidates: [], blocked: null };
    if (!words.length) {
        return nothing;
    }
    const negated = isNegated(text);
    const view = vocabulary.view;
    return guardNegation(
        understand(tokens, words, text, vocabulary, view) || nothing,
        negated,
    );
}

/**
 * @param {Token[]} tokens
 * @param {string[]} words
 * @param {string} text
 * @param {Vocabulary} vocabulary
 * @param {ViewTerms | null} view
 * @returns {Interpretation | null}
 */
function understand(tokens, words, text, vocabulary, view) {
    for (const [kind, phrases] of Object.entries(COMMAND_PHRASES)) {
        if (saysOneOf(words, phrases)) {
            const proposal = sentenceCommand(kind, view);
            if (proposal) {
                return single(text, proposal);
            }
        }
    }
    const number = parseNumber(words, vocabulary);
    if (number) {
        return single(text, number);
    }
    const viewSwitch = switchView(words, view);
    if (viewSwitch) {
        return single(text, viewSwitch);
    }
    if (OPEN_VERBS.has(words[0])) {
        const opened = openSomething(tokens.slice(1), text, vocabulary);
        if (opened) {
            return opened;
        }
    }
    const dictate = parseDictate(words, vocabulary);
    if (dictate) {
        return single(text, dictate);
    }
    if (view?.form) {
        const setField = parseSetField(tokens, text, view, vocabulary.today);
        if (setField) {
            return single(text, setField);
        }
        const button = parseButton(words, view);
        if (button) {
            return single(text, button);
        }
    }
    const clicked = parseClickLabel(words, vocabulary);
    if (clicked) {
        return single(text, clicked);
    }
    if (view && view.viewType !== "form") {
        const search = parseSearch(tokens, text, view, vocabulary.today);
        if (search) {
            return single(text, search);
        }
    }
    const menu = openSomething(tokens, text, vocabulary);
    if (menu && !menu.proposals[0]?.then && menu.proposals[0]?.kind === "open_menu") {
        return menu;
    }
    if (menu?.candidates.length) {
        return menu;
    }
    const command = parseCommand(words, vocabulary);
    return command ? single(text, command) : null;
}
