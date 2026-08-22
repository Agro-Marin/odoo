// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { DynamicGroupList } from "@web/model/relational_model/dynamic_group_list";
import { DynamicList } from "@web/model/relational_model/dynamic_list";
import { DYNAMIC_LIST_OWNER_SURFACE } from "@web/model/relational_model/dynamic_list_contract";
import { DynamicRecordList } from "@web/model/relational_model/dynamic_record_list";
import { StaticList } from "@web/model/relational_model/static_list";

describe.current.tags("headless");

describe("the DynamicList owner contract and the class agree", () => {
    test("DynamicList carries every operation the contract names", () => {
        const missing = DYNAMIC_LIST_OWNER_SURFACE.filter(
            (key) => !(key in DynamicList.prototype),
        );
        expect(missing).toEqual([], {
            message:
                "DYNAMIC_LIST_OWNER_SURFACE names something DynamicList no longer " +
                "has -- update the contract, and every module annotated with it",
        });
    });

    test("every member of the contract is an operation, not state", () => {
        const notMethods = DYNAMIC_LIST_OWNER_SURFACE.filter(
            (key) =>
                typeof (/** @type {any} */ (DynamicList.prototype)[key]) !== "function",
        );
        expect(notMethods).toEqual([], {
            message:
                "this surface is what a collaborator calls; state belongs in the " +
                "datapoint, not in the contract",
        });
    });

    test("both concrete lists inherit it — a group list is reached through it too", () => {
        for (const Class of [DynamicRecordList, DynamicGroupList]) {
            const missing = DYNAMIC_LIST_OWNER_SURFACE.filter(
                (key) => !(key in Class.prototype),
            );
            expect(missing).toEqual([], {
                message: `${Class.name} must answer the DynamicList contract`,
            });
        }
    });

    test("control: the contract is about the SERVER-backed list, not the x2many", () => {
        const shared = DYNAMIC_LIST_OWNER_SURFACE.filter(
            (key) => key in StaticList.prototype,
        );
        expect(shared).toEqual([], {
            message:
                "_multiSave / _resequence / _isRecordToDiscard / _onRecordDeselected " +
                "are the server-backed list's own; an x2many has no domain selection " +
                "and no multi-edit",
        });
    });
});
