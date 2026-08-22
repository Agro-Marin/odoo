// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { getSpecEvalContext } from "@web/model/relational_model/field_context";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { getFieldsSpec } from "@web/model/relational_model/field_spec";

describe.current.tags("headless");

describe("getSpecEvalContext", () => {
    test("resolves both the action-context names and the company/user names", () => {
        const activeFields = {
            trululu: makeActiveField({
                context:
                    "{'k_probe': probe, 'k_ccid': current_company_id, 'k_uid': uid, " +
                    "'k_get': context.get('probe')}",
            }),
        };
        const flds = { trululu: { type: "many2one", name: "trululu" } };
        const config = {
            context: { uid: 7, allowed_company_ids: [3], probe: 42 },
        };
        expect(getFieldsSpec(activeFields, flds, getSpecEvalContext(config))).toEqual({
            trululu: {
                fields: { display_name: {} },
                context: { k_probe: 42, k_ccid: 3, k_uid: 7, k_get: 42 },
            },
        });
    });
});
