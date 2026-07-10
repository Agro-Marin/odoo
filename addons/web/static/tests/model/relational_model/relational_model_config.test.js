// @ts-check

/**
 * Tests for the config-patching API of RelationalModel.
 *
 * ``_patchConfig`` must stay synchronous: 20+ call sites read the patched
 * config in the very next statement without awaiting. Exercised directly
 * on the prototype (no ``this``) without building a full model/env.
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
        // Guard against turning this async: every non-awaiting call site
        // would break silently as the config write moves to a later microtask.
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
