// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Component, xml } from "@odoo/owl";
import {
    defineModels,
    fields,
    models,
    mountWithSearch,
} from "@web/../tests/web_test_helpers";
import {
    SEARCH_COMPOSITION_BASE_SURFACE,
    SEARCH_COMPOSITION_CONDITIONAL_STATE,
    SEARCH_COMPOSITION_CONTRACT,
    SEARCH_COMPOSITION_ORDER,
} from "@web/search/search_composition_contract";
import { SearchModel } from "@web/search/search_model";

describe.current.tags("headless");

/**
 * The prototype chain of the composition, most-derived first: `SearchModel`,
 * then one level per mixin factory, then the `EventBus` the chain is applied
 * to. `Object.prototype` is dropped -- it belongs to no unit.
 *
 * @returns {object[]}
 */
function chain() {
    const levels = [];
    let proto = SearchModel.prototype;
    while (proto && proto !== Object.prototype) {
        levels.push(proto);
        proto = Object.getPrototypeOf(proto);
    }
    return levels;
}

/**
 * @param {object} proto
 * @returns {string[]}
 */
const own = (proto) => Object.getOwnPropertyNames(proto);

/**
 * @param {string} name
 * @returns {boolean}
 */
const resolves = (name) => chain().some((proto) => own(proto).includes(name));

const MODULES = SEARCH_COMPOSITION_ORDER;

class Partner extends models.Model {
    _name = "partner";
    foo = fields.Char();
}
defineModels([Partner]);

class Probe extends Component {
    static template = xml`<div class="o_probe"/>`;
    static props = ["*"];
}

/**
 * A real `SearchModel`, loaded the way a view loads one.
 *
 * @returns {Promise<any>}
 */
async function loadedSearchModel() {
    const component = await mountWithSearch(Probe, {
        resModel: "partner",
        searchViewId: false,
    });
    return component.env.searchModel;
}

describe("the composition contract and the composition agree", () => {
    test("every published operation resolves on the chain", () => {
        /** @type {string[]} */
        const missing = [];
        for (const module of MODULES) {
            for (const name of SEARCH_COMPOSITION_CONTRACT[module].published) {
                if (!resolves(name)) {
                    missing.push(`${module}: ${name}`);
                }
            }
        }
        expect(missing).toEqual([], {
            message:
                "a unit declares it publishes something the composition no " +
                "longer has -- update the contract, and the units annotated with it",
        });
    });

    test("every required operation resolves on the chain", () => {
        /** @type {string[]} */
        const missing = [];
        for (const module of MODULES) {
            for (const name of SEARCH_COMPOSITION_CONTRACT[module].requires) {
                if (!resolves(name)) {
                    missing.push(`${module}: ${name}`);
                }
            }
        }
        expect(missing).toEqual([], {
            message: "a unit requires an operation nothing in the chain defines",
        });
    });

    test("every required operation is published by some unit", () => {
        const offered = new Set(
            MODULES.flatMap((m) => SEARCH_COMPOSITION_CONTRACT[m].published),
        );
        /** @type {string[]} */
        const unoffered = [];
        for (const module of MODULES) {
            for (const name of SEARCH_COMPOSITION_CONTRACT[module].requires) {
                if (!offered.has(name)) {
                    unoffered.push(`${module}: ${name}`);
                }
            }
        }
        expect(unoffered).toEqual([], {
            message:
                "a unit reaches for an operation no unit offers -- either the " +
                "reach is into something private by accident, or a _PUBLISHED " +
                "list is short",
        });
    });

    test("shared state is state, not an operation the chain defines", () => {
        /** @type {string[]} */
        const onChain = [];
        for (const module of MODULES) {
            for (const name of SEARCH_COMPOSITION_CONTRACT[module].sharedState) {
                if (resolves(name)) {
                    onChain.push(`${module}: ${name}`);
                }
            }
        }
        expect(onChain).toEqual([], {
            message:
                "a _SHARED_STATE entry resolves on the prototype chain, so it " +
                "has an owner and belongs in _PUBLISHED or the base surface",
        });
    });

    test("no unit both publishes a name and treats it as shared state", () => {
        /** @type {string[]} */
        const both = [];
        for (const module of MODULES) {
            const entry = SEARCH_COMPOSITION_CONTRACT[module];
            const shared = new Set(entry.sharedState);
            for (const name of entry.published) {
                if (shared.has(name)) {
                    both.push(`${module}: ${name}`);
                }
            }
        }
        expect(both).toEqual([], {
            message:
                "a member cannot be both the published interface and the " +
                "working memory nobody outside should touch",
        });
    });

    test("the inherited base surface is inherited, and declared by no unit", () => {
        const declared = new Set(
            MODULES.flatMap((m) => SEARCH_COMPOSITION_CONTRACT[m].published),
        );
        for (const name of SEARCH_COMPOSITION_BASE_SURFACE) {
            expect(resolves(name)).toBe(true, {
                message: `${name} is declared as inherited but resolves nowhere`,
            });
            expect(declared.has(name)).toBe(false, {
                message: `${name} is inherited AND published by a unit`,
            });
        }
    });

    test("the chain is composed in the order the contract declares", () => {
        // Each unit is identified by the level that owns everything it
        // publishes. SEARCH_COMPOSITION_ORDER is innermost first, so the level
        // indices -- most-derived first -- must come out strictly decreasing.
        // This is what catches a reordering of the mixin factories, which
        // silently changes which unit's override of a shared name wins and
        // which `super` a call reaches.
        const levels = chain();
        /** @type {number[]} */
        const found = [];
        for (const module of MODULES) {
            const published = SEARCH_COMPOSITION_CONTRACT[module].published;
            if (!published.length) {
                continue;
            }
            const index = levels.findIndex((proto) =>
                published.every((name) => own(proto).includes(name)),
            );
            expect(index).not.toBe(-1, {
                message: `no single level of the chain owns all of ${module}'s published surface`,
            });
            found.push(index);
        }
        const descending = [...found].sort((a, b) => b - a);
        expect(found).toEqual(descending, {
            message:
                "the prototype chain does not run innermost-to-outermost in " +
                "SEARCH_COMPOSITION_ORDER -- the composition was reordered",
        });
    });
    test("every unconditional shared-state name exists on a loaded SearchModel", async () => {
        // The negative check above says these names are not on the prototype.
        // This is the other half, and the one that catches a _SHARED_STATE
        // entry naming something the model never actually has: 102 of the 105
        // are here the moment a model has loaded.
        const conditional = new Set(SEARCH_COMPOSITION_CONDITIONAL_STATE);
        const model = await loadedSearchModel();
        /** @type {string[]} */
        const missing = [];
        for (const module of MODULES) {
            for (const name of SEARCH_COMPOSITION_CONTRACT[module].sharedState) {
                if (!conditional.has(name) && !(name in model)) {
                    missing.push(name);
                }
            }
        }
        expect([...new Set(missing)].sort().join(" ")).toBe("", {
            message:
                "a _SHARED_STATE entry names something a loaded SearchModel " +
                "does not carry -- either it is conditional, and belongs in " +
                "SEARCH_COMPOSITION_CONDITIONAL_STATE with the condition " +
                "written down, or the contract is describing state that no " +
                "longer exists",
        });
    });

    test("the conditional shared state really is conditional", async () => {
        // Pins the classification in the other direction. A name that starts
        // being assigned unconditionally fails here until it leaves the list,
        // so the list cannot quietly become a place to park inconvenient
        // entries.
        const model = await loadedSearchModel();
        const present = SEARCH_COMPOSITION_CONDITIONAL_STATE.filter(
            (name) => name in model,
        );
        expect(present).toEqual([], {
            message:
                "a name declared conditional is present on a model loaded " +
                "without a search panel -- it is unconditional now, and the " +
                "positive check above should be covering it",
        });
    });

    test("every conditional name is declared as shared state by some unit", () => {
        const shared = new Set(
            MODULES.flatMap((m) => SEARCH_COMPOSITION_CONTRACT[m].sharedState),
        );
        const stray = SEARCH_COMPOSITION_CONDITIONAL_STATE.filter(
            (name) => !shared.has(name),
        );
        expect(stray).toEqual([], {
            message:
                "SEARCH_COMPOSITION_CONDITIONAL_STATE names something no unit " +
                "declares -- it is qualifying an entry that does not exist",
        });
    });
});
