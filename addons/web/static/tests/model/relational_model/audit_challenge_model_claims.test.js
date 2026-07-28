// @ts-check

/**
 * Adversarial verification of three audit claims about the model layer. Each
 * block states the claim, then tries to make it fail. Kept together because
 * they share no fixture — the point is the falsification attempt, not the
 * subject.
 */

import { describe, expect, test } from "@odoo/hoot";
import { Deferred } from "@web/core/utils/concurrency";
import { serializeCommands } from "@web/model/relational_model/command_builder";
import { DynamicGroupList } from "@web/model/relational_model/dynamic_group_list";
import { UrgentSaveCoordinator } from "@web/model/relational_model/urgent_save_coordinator";

describe("CLAIM: UrgentSaveCoordinator drains re-entrant runs only once", () => {
    test("a re-entrant run registered after the drain snapshot is still awaited", async () => {
        // The gap needs a precise ordering: the re-entrant must be registered
        // STRICTLY after ``Promise.allSettled`` captured its input list. A
        // re-entrant registered in the same microtask batch as the outer fn
        // lands in the first batch and was always drained correctly — that is
        // the control below. Only this ordering exposed the single-pass drain.
        const coordinator = new UrgentSaveCoordinator(null);
        const gate = new Deferred();
        const lateDone = new Deferred();
        let lateFinished = false;
        let activeWhenLateRegistered = null;

        const outer = coordinator.run(async () => {
            coordinator.run(async () => {
                await gate;
            });
        });

        // Let the finally park in its drain await.
        await new Promise((resolve) => setTimeout(resolve, 0));

        gate.then(() => {
            activeWhenLateRegistered = coordinator.isActive;
            coordinator.run(async () => {
                await lateDone;
                lateFinished = true;
            });
        });
        gate.resolve();

        // ``lateDone`` stays pending on purpose: the whole question is whether
        // run() resolves BEFORE it. Resolving it up front makes the test pass
        // against the buggy single-pass drain too, proving nothing.
        let outerSettled = false;
        outer.then(() => {
            outerSettled = true;
        });
        await new Promise((resolve) => setTimeout(resolve, 50));

        // The coordinator accepted it as re-entrant, so urgent mode must still
        // be covering it — run() must not have returned yet.
        expect(activeWhenLateRegistered).toBe(true);
        expect(outerSettled).toBe(false);
        expect(coordinator.isActive).toBe(true);
        expect(lateFinished).toBe(false);

        lateDone.resolve();
        await outer;
        expect(lateFinished).toBe(true);
        expect(coordinator.isActive).toBe(false);
    });

    test("a re-entrant run registered before the drain IS awaited (control)", async () => {
        const coordinator = new UrgentSaveCoordinator(null);
        const gate = new Deferred();
        let finished = false;

        const outer = coordinator.run(async () => {
            coordinator.run(async () => {
                await gate;
                finished = true;
            });
        });
        gate.resolve();
        await outer;

        expect(finished).toBe(true);
        expect(coordinator.isActive).toBe(false);
    });
});

describe("CLAIM: _ensureCorrectRecordCount drops the view context", () => {
    function makeGroupList({ count, limit, context }) {
        const list = Object.create(DynamicGroupList.prototype);
        /** @type {any} */
        const calls = [];
        Object.assign(list, {
            _config: { context, domain: [["active", "=", false]], limit },
            count,
            _nbRecordsMatchingDomain: null,
            model: {
                initialCountLimit: 10000,
                orm: {
                    searchCount: (resModel, domain, kwargs) => {
                        calls.push({ resModel, domain, kwargs });
                        return Promise.resolve(3);
                    },
                },
            },
        });
        Object.defineProperty(list, "resModel", { value: "account.tax" });
        return { list, calls };
    }

    test("the search_count carries no context at all", async () => {
        // An action context such as account_tax_views.xml's
        // {'active_test': False} lives in config.context.
        const { list, calls } = makeGroupList({
            count: 100,
            limit: 80,
            context: { active_test: false, lang: "en_US" },
        });
        expect(list.isRecordCountTrustable).toBe(false);

        await list._ensureCorrectRecordCount();

        expect(calls).toHaveLength(1);
        // orm.call merges only user.context when kwargs.context is absent, so
        // active_test never reaches the server and the count is taken with
        // active_test defaulting to true.
        expect(calls[0].kwargs.context).toEqual({ active_test: false, lang: "en_US" });
    });

    test("it does not fire while the group count is trustable (reachability gate)", async () => {
        const { list, calls } = makeGroupList({
            count: 12,
            limit: 80,
            context: { active_test: false },
        });
        expect(list.isRecordCountTrustable).toBe(true);

        await list._ensureCorrectRecordCount();

        expect(calls).toHaveLength(0);
    });
});

describe("CLAIM: an orphaned _unknownRecordCommands stash reaches the save payload", () => {
    test("deferred values are merged into a later UPDATE command", () => {
        const fields = {
            name: { name: "name", type: "char" },
            description: { name: "description", type: "char" },
        };
        const activeFields = {
            name: { readonly: "False" },
            description: { readonly: "False" },
        };
        // The orphan: a stash left behind by a rolled-back onchange.
        const unknownRecordCommands = {
            7: [[1, 7, { description: "from a change the user never committed" }]],
        };
        // A later, legitimate edit stages [UPDATE, 7] again.
        const commands = [[1, 7]];

        const result = serializeCommands(commands, {
            unknownRecordCommands,
            fields,
            activeFields,
            context: {},
            getRecord: () => ({ id: 7 }),
            getRecordChanges: () => ({ name: "what the user actually typed" }),
            convertUnityValues: (values) => ({ ...values }),
        });

        expect(result).toHaveLength(1);
        expect(result[0][0]).toBe(1);
        expect(result[0][1]).toBe(7);
        // The user's own edit is there — and so is the rolled-back value.
        expect(result[0][2].name).toBe("what the user actually typed");
        expect(result[0][2].description).toBe("from a change the user never committed");
    });
});
