// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    cloneActiveFields,
    combineModifiers,
    makeActiveField,
    patchActiveFields,
} from "@web/model/relational_model/field_metadata";
import { ListMembership } from "@web/model/relational_model/list_membership";
import { StaticList } from "@web/model/relational_model/static_list";

describe("combineModifiers", () => {
    test("is idempotent: combining a modifier with itself returns it unchanged", () => {
        expect(combineModifiers("qty > 0", "qty > 0", "OR")).toBe("qty > 0");
        expect(combineModifiers("qty > 0", "qty > 0", "AND")).toBe("qty > 0");
    });

    test("still validates the operator", () => {
        expect(() => combineModifiers("a", "a", /** @type {any} */ ("XOR"))).toThrow();
    });
});

describe("cloneActiveFields", () => {
    test("copies every container the merge helpers write into", () => {
        const source = {
            line_ids: {
                ...makeActiveField({ required: "qty > 0" }),
                related: {
                    activeFields: { qty: makeActiveField({ readonly: "a" }) },
                    fields: { qty: { type: "integer", name: "qty" } },
                },
            },
        };
        const clone = cloneActiveFields(source);
        expect(clone.line_ids).not.toBe(source.line_ids);
        expect(clone.line_ids.related).not.toBe(source.line_ids.related);
        expect(clone.line_ids.related.activeFields).not.toBe(
            source.line_ids.related.activeFields,
        );
        expect(clone.line_ids.related.fields).not.toBe(source.line_ids.related.fields);
        expect(clone.line_ids.related.activeFields.qty).not.toBe(
            source.line_ids.related.activeFields.qty,
        );

        patchActiveFields(clone.line_ids, {
            required: "other",
            related: {
                activeFields: { name: makeActiveField() },
                fields: { name: { type: "char", name: "name" } },
            },
        });
        expect(/** @type {any} */ (source.line_ids).required).toBe("qty > 0");
        expect("name" in source.line_ids.related.activeFields).toBe(false);
        expect("name" in source.line_ids.related.fields).toBe(false);
    });
});

describe("extendRecord activeFields purity", () => {
    function makeList() {
        const list = Object.create(StaticList.prototype);
        Object.assign(list, {
            _membership: new ListMembership(),
            _config: {
                activeFields: { name: makeActiveField({ required: "qty > 0" }) },
                fields: { name: { type: "char", name: "name" } },
                resModel: "child",
                context: {},
            },
            _extendedRecords: new Set(),
            model: {
                mutex: { exec: (fn) => fn() },
                _patchConfig: (config, patch) => Object.assign(config, patch),
            },
        });
        return list;
    }

    test("repeated extendRecord leaves the caller's params untouched", async () => {
        const list = makeList();
        const record = {
            id: 1,
            config: { activeFields: {}, fields: {} },
            _addSavePoint() {},
            extendActiveFields() {},
        };
        list._extendedRecords.add(record.id);

        const params = {
            activeFields: { name: makeActiveField({ required: "qty > 0" }) },
            fields: { name: { type: "char", name: "name" } },
        };
        const before = params.activeFields.name.required;

        for (let i = 0; i < 4; i++) {
            await list.extendRecord(params, record);
        }

        expect(params.activeFields.name.required).toBe(before);
        expect(record.config.activeFields.name.required).toBe(before);
    });
});
