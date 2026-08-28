// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    DOUBLE_ONLY_MEMBERS,
    doubleMembersFor,
} from "@web/../tests/search/search_doubles";
import {
    SEARCH_COMPOSITION_CONTRACT,
    SEARCH_COMPOSITION_ORDER,
} from "@web/search/search_composition_contract";

describe.current.tags("headless");

/** The units that have a double: everything in the chain except the host. */
const DOUBLED = SEARCH_COMPOSITION_ORDER.filter(
    (module) => module !== "search/search_model.js",
);

describe("the composition doubles and the contract agree", () => {
    test("a double is declared for every mixin in the chain", () => {
        /** @type {string[]} */
        const missing = [];
        for (const module of DOUBLED) {
            try {
                doubleMembersFor(module);
            } catch {
                missing.push(module);
            }
        }
        expect(missing).toEqual([], {
            message:
                "a mixin joined the composition without a double -- add one, " +
                "or the first suite that needs it will hand-roll another",
        });
    });

    test("every double covers everything its unit is declared to reach", () => {
        /** @type {string[]} */
        const uncovered = [];
        for (const module of DOUBLED) {
            const entry = SEARCH_COMPOSITION_CONTRACT[module];
            const members = doubleMembersFor(module);
            for (const name of [...entry.requires, ...entry.sharedState]) {
                if (!(name in members)) {
                    uncovered.push(`${module}: ${name}`);
                }
            }
        }
        expect(uncovered).toEqual([], {
            message:
                "a double has fallen behind its contract. The member reads " +
                "`undefined` at runtime and the suite still passes, which is " +
                "the whole failure mode this test exists to make loud",
        });
    });

    test("no double invents a member the composition does not have", () => {
        // Checked against the whole composition rather than the unit's own
        // reach: a double has to carry the machinery its own stubs run on --
        // favorites never touches `blockNotification` itself, but the
        // `_withNotificationsBlocked` the double hands it does. What must not
        // happen is a double modelling a member no unit declares at all, which
        // is a double describing a composition that does not exist.
        const permitted = new Set(DOUBLE_ONLY_MEMBERS);
        const declared = new Set(
            SEARCH_COMPOSITION_ORDER.flatMap((module) => [
                ...SEARCH_COMPOSITION_CONTRACT[module].requires,
                ...SEARCH_COMPOSITION_CONTRACT[module].sharedState,
                ...SEARCH_COMPOSITION_CONTRACT[module].published,
            ]),
        );
        /** @type {string[]} */
        const invented = [];
        for (const module of DOUBLED) {
            for (const name of Object.keys(doubleMembersFor(module))) {
                if (!declared.has(name) && !permitted.has(name)) {
                    invented.push(`${module}: ${name}`);
                }
            }
        }
        expect(invented).toEqual([], {
            message:
                "a double models a member no unit declares -- either the " +
                "contract is short, or the double is describing a composition " +
                "that does not exist. Test-only members go in DOUBLE_ONLY_MEMBERS",
        });
    });

    test("the notification channel a double supplies actually blocks", () => {
        // The one behaviour every mixin suite leans on, so it is worth pinning
        // rather than trusting: `_notify` is a no-op inside a blocked window
        // and records a step outside one.
        const members = doubleMembersFor("search/search_favorites_mixin.js");
        const model = /** @type {any} */ ({ ...members });
        model._notify();
        expect(model._notifications).toEqual(["notify"]);

        model._withNotificationsBlocked(() => {
            model._notify();
        });
        expect(model._notifications).toEqual(["notify"], {
            message: "a notification escaped a blocked window",
        });
        expect(model.blockNotification).toBe(false, {
            message: "the block window did not restore the previous state",
        });
    });
});
