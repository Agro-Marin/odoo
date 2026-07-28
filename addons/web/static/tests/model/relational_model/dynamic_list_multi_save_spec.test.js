// @ts-check

/**
 * The mass-edit read-back (``DynamicList._multiSave``) must build its
 * ``web_save`` specification under the SAME eval context as the single-record
 * read-back in ``record_save.save``.
 *
 * ``getFieldsSpec`` resolves a field's ``context`` attribute through
 * ``evalPartialContext``, which silently DROPS any key whose free variables it
 * cannot resolve. Called without an eval context (the historical 2-argument
 * call here) every ``uid`` / ``allowed_company_ids``-dependent field context
 * vanished from the mass-edit spec while surviving the single save — so the two
 * paths re-read the same records under different contexts.
 */

import { expect, test } from "@odoo/hoot";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
    onRpc,
    serverState,
    webModels,
} from "@web/../tests/web_test_helpers";

const { ResCompany, ResPartner, ResUsers } = webModels;

class Foo extends models.Model {
    name = fields.Char();
    int_field = fields.Integer();
    trululu = fields.Many2one({ relation: "foo" });

    _records = [
        { id: 1, name: "yop", int_field: 1 },
        { id: 2, name: "blip", int_field: 2 },
    ];
}

defineModels([Foo, ResCompany, ResPartner, ResUsers]);

test("the mass-edit read-back spec resolves uid-dependent field contexts", async () => {
    /** @type {any} */
    let spec;
    onRpc("web_save", ({ kwargs }) => {
        spec = kwargs.specification;
    });

    await mountView({
        resModel: "foo",
        type: "list",
        arch: `
            <list multi_edit="1">
                <field name="int_field"/>
                <field name="trululu" context="{'from_uid': uid}"/>
            </list>`,
    });

    await contains(".o_data_row:eq(0) .o_list_record_selector input").click();
    await contains(".o_data_row:eq(1) .o_list_record_selector input").click();
    await contains(".o_data_row:eq(0) .o_data_cell[name='int_field']").click();
    await contains(".o_field_widget[name=int_field] input").edit("64");
    await contains(".modal .btn-primary").click();

    expect(spec).not.toBe(undefined);
    expect(spec.trululu.context).toEqual({ from_uid: serverState.userId });
});
