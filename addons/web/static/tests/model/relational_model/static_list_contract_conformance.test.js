// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { StaticList } from "@web/model/relational_model/static_list";
import {
    INTERNAL_STATE_REACHED,
    STATIC_LIST_OWNER_SURFACE,
} from "@web/model/relational_model/static_list_contract";

describe.current.tags("headless");

describe("the StaticList owner contract and the class agree", () => {
    test("StaticList carries every operation the contract names", () => {
        const missing = STATIC_LIST_OWNER_SURFACE.filter(
            (key) => !(key in StaticList.prototype),
        );
        expect(missing).toEqual([], {
            message:
                "STATIC_LIST_OWNER_SURFACE names something StaticList no longer " +
                "has -- update the contract, and every module annotated with it",
        });
    });

    test("every `_` member of the contract is an operation, not state", () => {
        const notMethods = STATIC_LIST_OWNER_SURFACE.filter(
            (key) =>
                key.startsWith("_") &&
                typeof (/** @type {any} */ (StaticList.prototype)[key]) !== "function",
        );
        expect(notMethods).toEqual([], {
            message: "the private half of the owner surface must be operations",
        });
    });

    test("the internal-state list is disjoint from the contract", () => {
        const both = STATIC_LIST_OWNER_SURFACE.filter((key) =>
            INTERNAL_STATE_REACHED.includes(key),
        );
        expect(both).toEqual([], {
            message:
                "a member cannot be both the published interface and the " +
                "working memory nobody outside should touch",
        });
    });
});
