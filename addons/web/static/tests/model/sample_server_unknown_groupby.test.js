// @ts-check

/**
 * SampleServer must survive a group-by naming a field it has never heard of.
 *
 * ``_mockFormattedReadGroup`` always meant to skip such an axis — it guards on
 * ``if (type)`` — but destructured the schema entry one line before that guard,
 * so the guard could never execute and the lookup threw instead.
 * ``_populateExistingGroups`` / ``_tweakExistingGroups`` read the same entry
 * with no guard at all. All three now go through ``_resolveGroupBy``.
 *
 * Unknown axes are dropped. Dropping every axis degrades to a single ungrouped
 * bucket (``cartesian()`` of nothing yields one empty tuple), and real groups
 * are left exactly as the server sent them.
 *
 * These exercise SampleServer directly because no app-level trigger is known:
 * a view passes one ``fields`` object to both ``buildSampleORM`` and the model
 * config, so runtime-added property axes are visible here too — see
 * sample_property_groupby.test.js, which passes with or without the helper.
 * What is fixed is a guard that could not run, not a reproduced failure.
 */

import { describe, expect, test } from "@odoo/hoot";
import { SampleServer } from "@web/model/sample_server";

describe.current.tags("headless");

const fields = {
    id: { string: "ID", type: "integer" },
    name: { string: "Name", type: "char" },
    stage: { string: "Stage", type: "selection", selection: [["a", "A"]] },
};

describe("SampleServer with an unknown group-by", () => {
    test("an unknown axis degrades to one ungrouped bucket", () => {
        const server = new SampleServer("res.partner", fields);

        const result = server.mockRpc({
            model: "res.partner",
            method: "web_read_group",
            groupBy: ["props.my_prop"],
            aggregates: [],
        });

        expect(result.length).toBe(1);
        expect(result.groups[0].__count).toBe(SampleServer.MAIN_RECORDSET_SIZE);
    });

    test("a known axis alongside an unknown one still groups by the known one", () => {
        const server = new SampleServer("res.partner", fields);

        const result = server.mockRpc({
            model: "res.partner",
            method: "web_read_group",
            groupBy: ["stage", "props.my_prop"],
            aggregates: [],
        });

        // grouped on "stage" only — the unknown axis contributes no dimension
        expect(result.length).toBe(1);
        expect(result.groups[0].stage).toBe("a");
        expect(result.groups[0].__count).toBe(SampleServer.MAIN_RECORDSET_SIZE);
    });

    test("a boolean progress-bar axis keys as True/False", () => {
        const server = new SampleServer("res.partner", {
            ...fields,
            flag: { string: "Flag", type: "boolean" },
            state: { string: "State", type: "selection", selection: [["ok", "Ok"]] },
        });

        const data = server.mockRpc({
            model: "res.partner",
            method: "read_progress_bar",
            group_by: "flag",
            progress_bar: { field: "state", colors: { ok: "success" } },
        });

        expect(Object.keys(data).sort()).toEqual(["False", "True"]);
        expect(data.True.ok + data.False.ok).toBe(SampleServer.MAIN_RECORDSET_SIZE);
    });

    test("existing real groups are left untouched when the axis is unknown", () => {
        const server = new SampleServer("res.partner", fields);
        const realGroups = [{ "props.my_prop": "x", __count: 7 }];
        server.setExistingGroups(realGroups);

        const result = server.mockRpc({
            model: "res.partner",
            method: "web_read_group",
            groupBy: ["props.my_prop"],
            aggregates: [],
        });

        expect(result.groups).toEqual(realGroups);
        expect(result.groups[0].__count).toBe(7);
    });
});
