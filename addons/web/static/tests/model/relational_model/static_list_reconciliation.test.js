// @ts-check

/**
 * Pure unit tests for StaticList's virtualId -> resId reconciliation
 * (snapshotCreateReconciliation / resolveCreatedResId), the model-owned
 * replacement for x2many_field.switchToForm's former private-command-log poke.
 *
 * Uses Object.create(StaticList.prototype) with hand-built _commands/config —
 * the two methods only read this._commands, this.resIds and record._virtualId.
 */

import { describe, expect, test } from "@odoo/hoot";
import { x2ManyCommands } from "@web/model/relational_model/commands";
import { StaticList } from "@web/model/relational_model/static_list";

function makeList({ commands, resIds }) {
    const list = Object.create(StaticList.prototype);
    list._commands = commands;
    // ``config`` is a getter over ``_config`` (DataPoint); the ``resIds`` getter
    // reads ``this.config.resIds``.
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
            resIds: [3], // one pre-existing linked record
        });
        // Snapshot BEFORE the save clears the CREATE commands.
        const token = list.snapshotCreateReconciliation();
        // web_save assigns resIds in create-command order.
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
        // Server returned ids not in array order; the nth CREATE maps to the
        // nth-smallest new id.
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
        // A create() override added TWO rows for ONE CREATE command: ambiguous,
        // so the caller surfaces "save first" instead of guessing.
        list.config.resIds = [10, 11];

        expect(list.resolveCreatedResId(token, { _virtualId: "virtual_1" })).toBe(
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
