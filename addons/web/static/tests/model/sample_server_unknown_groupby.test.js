// @ts-check

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
