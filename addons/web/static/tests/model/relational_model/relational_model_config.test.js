// @ts-check

/**
 * Tests for the config-patching API of RelationalModel
 * (relational_model.js).
 *
 * ``_patchConfig`` was split out of the historical ``_updateConfig`` so
 * that its synchrony is a CONTRACT rather than an accident: 20+ call
 * sites (mode switches, resId commits after save, limit/offset
 * bookkeeping, group fold state, ...) read the patched config in the
 * very next statement, without awaiting. These tests pin that contract.
 *
 * ``_patchConfig`` deliberately uses no model state (no ``this``), so it
 * is exercised here directly on the prototype without building a full
 * model/env.
 */

import { describe, expect, test } from "@odoo/hoot";
import { RelationalModel } from "@web/model/relational_model/relational_model";

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
        // The patched values MUST be readable in the very next statement
        // (call sites do not await).
        expect(config.mode).toBe("edit");
        expect(config.resId).toBe(42);
        // No promise is returned — there is nothing to await.
        expect(result).toBe(undefined);
    });

    test("is not an async function (guard against reintroducing await)", () => {
        // If someone turns _patchConfig into an async function (or makes it
        // return a promise), every non-awaiting call site breaks silently:
        // the config write moves to a later microtask. Fail loudly here
        // instead.
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
