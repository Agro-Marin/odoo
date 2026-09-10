// @ts-check

import { makeMockEnv, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { RelationalRecord } from "@web/model/relational_model/record";
import { RelationalModel } from "@web/model/relational_model/relational_model";

/** @param {Partial<Pick<RelationalModel, "loadRecords" | "loadNewRecord">>} overrides */
export async function makeTestRelationalModel(overrides) {
    const env = await makeMockEnv();
    const model = new RelationalModel(
        env,
        {
            config: {
                resModel: "res.partner",
                fields: {},
                activeFields: {},
                fieldsToAggregate: [],
                isMonoRecord: false,
                isRoot: true,
                context: {},
                domain: [],
                groupBy: [],
                orderBy: [],
            },
        },
        { orm: env.services.orm },
    );
    patchWithCleanup(model, overrides);
    return model;
}

/** @param {number} [resId] */
export async function makeTestRecordWithLines(resId = 1) {
    const model = await makeTestRelationalModel({
        loadNewRecord: async () => ({ display_name: "" }),
    });
    return new RelationalRecord(
        model,
        {
            ...model.config,
            resId,
            resIds: [resId],
            isMonoRecord: true,
            isRoot: false,
            mode: "edit",
            fields: {
                lines: { name: "lines", type: "one2many", relation: "res.partner" },
            },
            activeFields: {
                lines: {
                    ...makeActiveField(),
                    related: {
                        fields: {
                            display_name: { name: "display_name", type: "char" },
                        },
                        activeFields: { display_name: makeActiveField() },
                    },
                },
            },
        },
        { id: resId, lines: [] },
        {},
    );
}
