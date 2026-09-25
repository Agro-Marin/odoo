// @ts-check
/** @odoo-module native */

import {
    buttonProposal,
    commandProposal,
    openMenu,
    RISK,
    searchProposal,
    sentenceCommand,
    setFieldProposal,
    switchViewProposal,
} from "./interpreter.js";

const MAX_MENUS = 250;
const MODEL_PERIODS = {
    month: "this month",
    "month-1": "last month",
    year: "this year",
    "year-1": "last year",
};
const SENTENCE_ACTIONS = {
    home: ["open_home", "Open the home screen"],
    back: ["back", "Go back"],
    next: ["next", "Next record"],
    previous: ["previous", "Previous record"],
    new: ["new_record", "Create a new record"],
    save: ["save", "Save the record"],
    discard: ["discard", "Discard the changes"],
    clear_search: ["clear_search", "Remove every search filter"],
};

/**
 * @typedef {import("./interpreter.js").Proposal} Proposal
 * @typedef {import("./vocabulary.js").Vocabulary} Vocabulary
 * @typedef {{ id: string, label: string, value?: boolean }} Choice
 * @typedef {{ id: string, value?: string }} ChosenAction
 */

/**
 * Everything the user could ask for right now, as ids a model may only pick
 * from: it names no record, no field and no button the screen does not have.
 *
 * @param {Vocabulary} vocabulary
 * @returns {Choice[]}
 */
export function choicesOf(vocabulary) {
    const view = vocabulary.view;
    /** @type {Choice[]} */
    const choices = [];
    for (const [id, [kind, label]] of Object.entries(SENTENCE_ACTIONS)) {
        if (sentenceCommand(kind, view)) {
            choices.push({ id, label });
        }
    }
    const menus = [
        ...vocabulary.menus.filter((term) => term.isApp || term.inCurrentApp),
        ...vocabulary.menus.filter((term) => !term.isApp && !term.inCurrentApp),
    ].slice(0, MAX_MENUS);
    for (const term of menus) {
        const index = vocabulary.menus.indexOf(term);
        const label = term.isApp ? term.label : `${term.label} (${term.appLabel})`;
        choices.push({ id: `menu:${index}`, label: `Open ${label}` });
    }
    if (!view) {
        return choices;
    }
    for (const viewType of view.viewTypes) {
        if (viewType !== view.viewType) {
            choices.push({
                id: `view:${viewType}`,
                label: `Show the ${viewType} view`,
            });
        }
    }
    for (const filter of view.filters) {
        choices.push({ id: `filter:${filter.name}`, label: `Filter: ${filter.label}` });
    }
    for (const dateFilter of view.dateFilters) {
        for (const [generatorId, when] of Object.entries(MODEL_PERIODS)) {
            if (dateFilter.generatorIds.includes(generatorId)) {
                choices.push({
                    id: `period:${dateFilter.name}:${generatorId}`,
                    label: `${dateFilter.label}: ${when}`,
                });
            }
        }
    }
    for (const groupBy of view.groupBys) {
        choices.push({
            id: `groupby:${groupBy.fieldName}`,
            label: `Group by ${groupBy.label}`,
        });
    }
    for (const field of view.searchFields) {
        choices.push({
            id: `search:${field.fieldName}`,
            label: `Search ${field.label} for the value`,
            value: true,
        });
    }
    for (const field of view.form?.fields || []) {
        choices.push({
            id: `set:${field.name}`,
            label: `Set ${field.label} to the value`,
            value: true,
        });
    }
    for (const [index, button] of (view.form?.buttons || []).entries()) {
        choices.push({ id: `button:${index}`, label: `Press ${button.label}` });
    }
    for (const [index, command] of vocabulary.commands.entries()) {
        choices.push({ id: `command:${index}`, label: command.name });
    }
    return choices;
}

/**
 * The model's picks as the same proposals the grammar makes, so they carry
 * the same risks. Opening a menu leaves the view the other picks were about,
 * so it is taken alone; at most one pick waits for a confirmation.
 *
 * @param {ChosenAction[]} actions
 * @param {Vocabulary} vocabulary
 * @returns {Proposal[]}
 */
export function proposalsFromChoices(actions, vocabulary) {
    const offered = new Set(choicesOf(vocabulary).map((choice) => choice.id));
    const view = vocabulary.view;
    /** @type {Proposal[]} */
    const proposals = [];
    /** @type {{ filters: string[], dateFilters: any[], groupBys: string[], fieldSearches: any[] }} */
    const spec = { filters: [], dateFilters: [], groupBys: [], fieldSearches: [] };
    /** @type {string[]} */
    const labels = [];
    for (const { id, value = "" } of actions) {
        if (!offered.has(id)) {
            continue;
        }
        const [kind, key, extra] = id.split(":");
        if (kind === "menu") {
            return [openMenu(vocabulary.menus[Number(key)])];
        }
        if (kind in SENTENCE_ACTIONS) {
            const command = sentenceCommand(
                SENTENCE_ACTIONS[/** @type {keyof SENTENCE_ACTIONS} */ (kind)][0],
                view,
            );
            if (command) {
                proposals.push(command);
            }
        } else if (kind === "view") {
            proposals.push(switchViewProposal(key));
        } else if (kind === "filter") {
            const filter = view?.filters.find((term) => term.name === key);
            spec.filters.push(key);
            labels.push(filter?.label || key);
        } else if (kind === "period") {
            const dateFilter = view?.dateFilters.find((term) => term.name === key);
            spec.dateFilters.push({ name: key, generatorIds: [extra] });
            labels.push(
                `${dateFilter?.label || key}: ${MODEL_PERIODS[/** @type {keyof MODEL_PERIODS} */ (extra)]}`,
            );
        } else if (kind === "groupby") {
            const groupBy = view?.groupBys.find((term) => term.fieldName === key);
            spec.groupBys.push(key);
            labels.push(`Group by ${groupBy?.label || key}`);
        } else if (kind === "search" && value.trim()) {
            const field = view?.searchFields.find((term) => term.fieldName === key);
            spec.fieldSearches.push({ fieldName: key, value: value.trim() });
            labels.push(`${field?.label || key}: ${value.trim()}`);
        } else if (kind === "set") {
            const field = view?.form?.fields.find((term) => term.name === key);
            const proposal =
                field && setFieldProposal(field, value.trim(), vocabulary.today);
            if (proposal) {
                proposals.push(proposal);
            }
        } else if (kind === "button") {
            const button = view?.form?.buttons[Number(key)];
            if (button) {
                proposals.push(buttonProposal(button, view?.form?.displayName));
            }
        } else if (kind === "command") {
            proposals.push(commandProposal(vocabulary.commands[Number(key)]));
        }
    }
    if (labels.length) {
        proposals.unshift(searchProposal(spec, labels));
    }
    const commit = proposals.find((proposal) => proposal.risk === RISK.COMMIT);
    return proposals.filter(
        (proposal) => proposal.risk !== RISK.COMMIT || proposal === commit,
    );
}
