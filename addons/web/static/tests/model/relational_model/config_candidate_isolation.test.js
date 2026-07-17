// @ts-check

/**
 * Candidate-config isolation tests (``computeNextConfig`` + ``cloneGroupTree``
 * + ``postprocessReadGroup``).
 *
 * Data is loaded against CANDIDATE configs and committed on success.
 * ``KeepLast`` drops a superseded load's result but cannot stop its
 * continuation: ``postprocessReadGroup`` still runs when the stale RPC lands
 * and mutates group sub-configs (domain/context/fold/offset) in place. The
 * candidate must therefore own its own group containers — otherwise a
 * superseded load rewrites the state the winning load just committed, and the
 * next group fold/pager fetch runs with a stale domain.
 */

import { describe, expect, test } from "@odoo/hoot";
import {
    cloneGroupTree,
    computeNextConfig,
} from "@web/model/relational_model/config_transitions";
import { postprocessReadGroup } from "@web/model/relational_model/group_postprocessor";

const DEPS = { hasRoot: true };

const POSTPROCESS_DEPS = {
    getPropertyDefinition: async () => {},
    groupByInfo: {},
    initialLimit: 40,
    initialGroupsLimit: 10,
    defaultGroupLimit: 10,
};

function makeCommittedConfig() {
    return {
        isMonoRecord: false,
        resModel: "task",
        fields: { name: { type: "char", name: "name" } },
        activeFields: {},
        fieldsToAggregate: [],
        context: {},
        domain: [],
        groupBy: ["name"],
        orderBy: [],
        offset: 0,
        limit: 80,
        groups: {},
    };
}

function makeGroupData(name, count = 1) {
    return {
        __count: count,
        __extra_domain: [["name", "=", name]],
        __records: [],
        name,
    };
}

async function seedGroups(config, names) {
    const response = {
        groups: names.map((name) => makeGroupData(name)),
        length: names.length,
    };
    return postprocessReadGroup(config, response, POSTPROCESS_DEPS);
}

describe("candidate config isolation", () => {
    test("cloneGroupTree copies containers but shares field definitions", () => {
        const fields = { name: { type: "char", name: "name" } };
        const activeFields = {};
        const groups = {
            A: {
                fields,
                activeFields,
                value: "A",
                isFolded: false,
                record: { resId: 7 },
                list: {
                    fields,
                    activeFields,
                    domain: [["name", "=", "A"]],
                    offset: 40,
                    groups: {
                        sub: {
                            fields,
                            activeFields,
                            value: "sub",
                            list: { fields, activeFields, groups: {} },
                        },
                    },
                },
            },
        };
        const cloned = cloneGroupTree(groups);
        // Containers are fresh objects at every level…
        expect(cloned.A).not.toBe(groups.A);
        expect(cloned.A.list).not.toBe(groups.A.list);
        expect(cloned.A.record).not.toBe(groups.A.record);
        expect(cloned.A.list.groups.sub).not.toBe(groups.A.list.groups.sub);
        expect(cloned.A.list.groups.sub.list).not.toBe(groups.A.list.groups.sub.list);
        // …but the shared immutable references are kept.
        expect(cloned.A.fields).toBe(fields);
        expect(cloned.A.activeFields).toBe(activeFields);
        expect(cloned.A.list.fields).toBe(fields);
        // Values are preserved.
        expect(cloned.A.list.offset).toBe(40);
        expect(cloned.A.isFolded).toBe(false);
    });

    test("computeNextConfig clones the groups tree when groupBy is unchanged", async () => {
        const committed = makeCommittedConfig();
        await seedGroups(committed, ["A", "B"]);

        const candidate = computeNextConfig(committed, {}, DEPS);

        expect(candidate.groups).not.toBe(committed.groups);
        expect(candidate.groups.A).not.toBe(committed.groups.A);
        expect(candidate.groups.A.list).not.toBe(committed.groups.A.list);
        // Pagination/fold state opened by the user is still carried over.
        expect(candidate.groups.A.list.limit).toBe(committed.groups.A.list.limit);
        expect(candidate.groups.A.isFolded).toBe(committed.groups.A.isFolded);
    });

    test("computeNextConfig still drops the groups tree when groupBy changes", async () => {
        const committed = makeCommittedConfig();
        await seedGroups(committed, ["A"]);
        const candidate = computeNextConfig(committed, { groupBy: [] }, DEPS);
        expect("groups" in candidate).toBe(false);
    });

    test("domain-change offset reset stays on the candidate", async () => {
        const committed = makeCommittedConfig();
        await seedGroups(committed, ["A"]);
        committed.groups.A.list.offset = 40;

        const candidate = computeNextConfig(
            committed,
            { domain: [["x", "=", 1]] },
            DEPS,
        );

        expect(candidate.groups.A.list.offset).toBe(0);
        // Without candidate isolation, resetOffset recursed into the
        // committed config's group lists.
        expect(committed.groups.A.list.offset).toBe(40);
    });

    test("a superseded load's postprocess cannot clobber the winning config", async () => {
        const committed = makeCommittedConfig();
        await seedGroups(committed, ["A"]);

        // Two racing root loads: A (stale) starts first, B (fresh) starts
        // second and wins; A's RPC resolves late and its postprocess runs
        // after B committed.
        const staleCandidate = computeNextConfig(
            committed,
            { domain: [["stale", "=", 1]] },
            DEPS,
        );
        const winningCandidate = computeNextConfig(
            committed,
            { domain: [["fresh", "=", 1]] },
            DEPS,
        );

        await seedGroups(winningCandidate, ["A"]);
        const winningDomain = winningCandidate.groups.A.list.domain;
        expect(JSON.stringify(winningDomain)).toInclude("fresh");

        // The stale load's continuation lands late.
        await seedGroups(staleCandidate, ["A"]);

        // The winning (now committed) config is untouched: same object,
        // same domain — the next group fold/pager fetch stays fresh.
        expect(winningCandidate.groups.A.list.domain).toBe(winningDomain);
        expect(JSON.stringify(winningCandidate.groups.A.list.domain)).toInclude(
            "fresh",
        );
        expect(JSON.stringify(winningCandidate.groups.A.list.domain)).not.toInclude(
            "stale",
        );
        // The stale candidate mutated only its own discarded copy.
        expect(JSON.stringify(staleCandidate.groups.A.list.domain)).toInclude("stale");
    });
});
