// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Component, xml } from "@odoo/owl";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { useActiveActions } from "@web/fields/relational/relational_active_actions";

describe.current.tags("headless");

/**
 * @param {Parameters<typeof useActiveActions>[0]} params
 * @returns {Promise<any>}
 */
async function compute(params) {
    /** @type {any} */
    let actions;
    class Probe extends Component {
        static template = xml`<t/>`;
        static props = ["*"];
        setup() {
            actions = useActiveActions(params);
        }
    }
    await mountWithCleanup(Probe, { props: { record: {} } });
    return actions;
}

describe("crud options", () => {
    test("an absent option allows the action", async () => {
        const actions = await compute({
            fieldType: "one2many",
            getEvalParams: () => ({ readonly: false }),
        });
        expect(actions.create).toBe(true);
        expect(actions.delete).toBe(true);
        expect(actions.write).toBe(true);
    });

    test("a domain option is evaluated against the eval context", async () => {
        const params = (bar) => ({
            fieldType: /** @type {const} */ ("one2many"),
            crudOptions: { create: [["bar", "=", true]] },
            getEvalParams: () => ({ readonly: false, evalContext: { bar } }),
        });
        expect((await compute(params(true))).create).toBe(true);
        expect((await compute(params(false))).create).toBe(false);
    });

    test("readonly overrides every permission except many2many write", async () => {
        const readonlyO2M = await compute({
            fieldType: "one2many",
            getEvalParams: () => ({ readonly: true }),
        });
        expect(readonlyO2M).toInclude("create");
        expect(readonlyO2M.create).toBe(false);
        expect(readonlyO2M.delete).toBe(false);
        expect(readonlyO2M.write).toBe(false);

        const readonlyM2M = await compute({
            fieldType: "many2many",
            getEvalParams: () => ({ readonly: true }),
        });
        expect(readonlyM2M.write).toBe(true);
        expect(readonlyM2M.link).toBe(false);
        expect(readonlyM2M.unlink).toBe(false);
    });
});

describe("sub-view intersection", () => {
    test("the sub-view can only take an action away, never grant one", async () => {
        const denied = await compute({
            fieldType: "one2many",
            subViewActiveActions: { create: false },
            getEvalParams: () => ({ readonly: false }),
        });
        expect(denied.create).toBe(false);

        const refused = await compute({
            fieldType: "one2many",
            subViewActiveActions: { create: true },
            crudOptions: { create: [["bar", "=", true]] },
            getEvalParams: () => ({ readonly: false, evalContext: { bar: false } }),
        });
        expect(refused.create).toBe(false);
    });

    test("a key the sub-view does not mention is left alone", async () => {
        const actions = await compute({
            fieldType: "one2many",
            subViewActiveActions: { create: false },
            getEvalParams: () => ({ readonly: false }),
        });
        expect(actions.delete).toBe(true);
    });
});

describe("edit and onDelete", () => {
    test("edit comes from the eval params, falling back to the crud option", async () => {
        expect(
            (
                await compute({
                    fieldType: "one2many",
                    crudOptions: { edit: false },
                    getEvalParams: () => ({ readonly: false, edit: true }),
                })
            ).edit,
        ).toBe(true);

        expect(
            (
                await compute({
                    fieldType: "one2many",
                    crudOptions: { edit: "from-option" },
                    getEvalParams: () => ({ readonly: false }),
                })
            ).edit,
        ).toBe("from-option");
    });

    test("onDelete is withheld unless something can actually delete", async () => {
        const onDelete = () => {};

        expect(
            (
                await compute({
                    fieldType: "one2many",
                    crudOptions: { onDelete },
                    getEvalParams: () => ({ readonly: false }),
                })
            ).onDelete,
        ).toBe(onDelete);

        expect(
            (
                await compute({
                    fieldType: "one2many",
                    crudOptions: { onDelete },
                    getEvalParams: () => ({ readonly: true }),
                })
            ).onDelete,
        ).toBe(null);

        expect(
            (
                await compute({
                    fieldType: "many2many",
                    crudOptions: { onDelete, unlink: [["bar", "=", true]] },
                    getEvalParams: () => ({
                        readonly: false,
                        evalContext: { bar: false },
                    }),
                })
            ).onDelete,
        ).toBe(null);
    });
});

test("link and unlink exist only for many2many", async () => {
    const o2m = await compute({
        fieldType: "one2many",
        getEvalParams: () => ({ readonly: false }),
    });
    expect("link" in o2m).toBe(false);
    expect("unlink" in o2m).toBe(false);

    const m2m = await compute({
        fieldType: "many2many",
        getEvalParams: () => ({ readonly: false }),
    });
    expect(m2m.link).toBe(true);
    expect(m2m.unlink).toBe(true);
});
