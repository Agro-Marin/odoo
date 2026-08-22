// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { RelationalModel } from "@web/model/relational_model/relational_model";

describe.current.tags("headless");

describe("RelationalModel._patchConfig", () => {
    test("is synchronous: patch is visible immediately, no await", () => {
        const config = {
            activeFields: {},
            fields: {},
            mode: "readonly",
            resId: false,
        };
        const result = RelationalModel.prototype._patchConfig.call(null, config, {
            mode: "edit",
            resId: 42,
        });
        expect(config.mode).toBe("edit");
        expect(config.resId).toBe(42);
        expect(result).toBe(undefined);
    });

    test("is not an async function (guard against reintroducing await)", () => {
        expect(RelationalModel.prototype._patchConfig.constructor.name).toBe(
            "Function",
        );
    });

    test("keeps keys not present in the patch", () => {
        const config = {
            activeFields: {},
            fields: {},
            limit: 80,
            offset: 40,
        };
        RelationalModel.prototype._patchConfig.call(null, config, {
            offset: 0,
        });
        expect(config.limit).toBe(80);
        expect(config.offset).toBe(0);
    });
});
