// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { x2ManyCommands } from "@web/core/network/commands";
import { StaticList } from "@web/model/relational_model/static_list";

describe.current.tags("headless");

/** @param {{ commands: any, resIds: any }} params */
function makeList({ commands, resIds }) {
    const list = Object.create(StaticList.prototype);
    list._commands = commands;
    list._config = { resIds };
    return list;
}

describe("StaticList create reconciliation", () => {
    test("resolveCreatedResId maps each virtualId to its create-order resId", () => {
        const list = makeList({
            commands: [
                [x2ManyCommands.CREATE, "virtual_1"],
                [x2ManyCommands.CREATE, "virtual_2"],
            ],
            resIds: [3],
        });
        const token = list.snapshotCreateReconciliation();
        list.config.resIds = [3, 10, 11];

        expect(list.resolveCreatedResId(token, { _virtualId: "virtual_1" })).toBe(10);
        expect(list.resolveCreatedResId(token, { _virtualId: "virtual_2" })).toBe(11);
    });

    test("resolveCreatedResId sorts new resIds so out-of-order ids still map by rank", () => {
        const list = makeList({
            commands: [
                [x2ManyCommands.CREATE, "virtual_1"],
                [x2ManyCommands.CREATE, "virtual_2"],
            ],
            resIds: [],
        });
        const token = list.snapshotCreateReconciliation();
        list.config.resIds = [21, 20];

        expect(list.resolveCreatedResId(token, { _virtualId: "virtual_1" })).toBe(20);
        expect(list.resolveCreatedResId(token, { _virtualId: "virtual_2" })).toBe(21);
    });

    test("resolveCreatedResId returns undefined on a row-count mismatch", () => {
        const list = makeList({
            commands: [[x2ManyCommands.CREATE, "virtual_1"]],
            resIds: [],
        });
        const token = list.snapshotCreateReconciliation();
        list.config.resIds = [10, 11];

        expect(list.resolveCreatedResId(token, { _virtualId: "virtual_1" })).toBe(
            undefined,
        );
    });

    test("resolveCreatedResId returns undefined when no CREATE claims the record", () => {
        const list = makeList({
            commands: [[x2ManyCommands.CREATE, "virtual_1"]],
            resIds: [3],
        });
        const token = list.snapshotCreateReconciliation();
        list.config.resIds = [3, 10];

        expect(list.resolveCreatedResId(token, { _virtualId: "virtual_9" })).toBe(
            undefined,
        );
    });

    test("snapshot ignores non-CREATE commands (LINK/UPDATE) when counting", () => {
        const list = makeList({
            commands: [
                [x2ManyCommands.LINK, 4],
                [x2ManyCommands.CREATE, "virtual_1"],
                [x2ManyCommands.UPDATE, 3],
            ],
            resIds: [3, 4],
        });
        const token = list.snapshotCreateReconciliation();
        expect(token.createVirtualIds).toEqual(["virtual_1"]);
        list.config.resIds = [3, 4, 12];

        expect(list.resolveCreatedResId(token, { _virtualId: "virtual_1" })).toBe(12);
    });
});
