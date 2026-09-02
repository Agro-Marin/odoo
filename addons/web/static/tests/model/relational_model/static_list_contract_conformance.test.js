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

    test("the owner surface is operations, plus the five accessors an owner reads", () => {
        const accessors = STATIC_LIST_OWNER_SURFACE.filter(
            (key) =>
                typeof Object.getOwnPropertyDescriptor(StaticList.prototype, key)
                    ?.value !== "function",
        );
        expect(accessors).toEqual(
            ["cachedRecords", "hasStagedCommands", "orderBy", "pendingCommands"],
            { message: "an owner surface member is an operation or a named accessor" },
        );
        expect(STATIC_LIST_OWNER_SURFACE.filter((key) => key.startsWith("_"))).toEqual(
            [],
            {
                message:
                    "a member an owner reaches is public; the underscore was the lie",
            },
        );
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
