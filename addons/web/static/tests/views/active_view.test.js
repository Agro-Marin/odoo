// @ts-check

import { expect, test } from "@odoo/hoot";
import { animationFrame, mockDate } from "@odoo/hoot-mock";
import {
    defineModels,
    fields,
    getFacetTexts,
    getService,
    models,
    mountView,
    mountWebClient,
} from "@web/../tests/web_test_helpers";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";

class Partner extends models.Model {
    _name = "partner";
    name = fields.Char();
    is_company = fields.Boolean({ string: "Is company" });
    date = fields.Date({ string: "Date" });
    country = fields.Char({ string: "Country", groupable: true });
    parent_id = fields.Many2one({ string: "Parent", relation: "partner" });
    _records = [
        { id: 1, name: "Acme", is_company: true, country: "MX", date: "2019-06-02" },
        { id: 2, name: "Bea", country: "MX", parent_id: 1, date: "2019-07-12" },
    ];
    _views = {
        form: `<form><field name="name"/></form>`,
    };
}

defineModels([Partner]);

const SEARCH_ARCH = `
    <search>
        <field name="name"/>
        <filter name="companies" string="Companies" domain="[('is_company', '=', True)]"/>
        <separator/>
        <filter name="date" string="Date" date="date"/>
        <filter name="by_country" string="Country" context="{'group_by': 'country'}"/>
        <filter name="by_date" string="Date" context="{'group_by': 'date'}"/>
    </search>`;

/** @returns {import("@web/views/active_view").ActiveView} */
function currentView() {
    const view = getService("active_view").current;
    expect(view).not.toBe(null);
    return /** @type {any} */ (view);
}

test("a list view is the current view, with its search model and controller", async () => {
    await mountView({
        type: "list",
        resModel: "partner",
        arch: `<list><field name="name"/></list>`,
    });
    const view = currentView();
    expect(view.config.viewType).toBe("list");
    expect(view.searchModel.resModel).toBe("partner");
    expect(view.controller.model.root.records).toHaveLength(2);
});

test("a form view exposes the record it shows", async () => {
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 2,
        arch: `<form><field name="name"/></form>`,
    });
    const view = currentView();
    expect(view.config.viewType).toBe("form");
    expect(view.controller.model.root.data.name).toBe("Bea");
});

test("a form in a dialog is the current view until the dialog closes", async () => {
    await mountView({
        type: "list",
        resModel: "partner",
        arch: `<list><field name="name"/></list>`,
    });
    const close = getService("dialog").add(FormViewDialog, {
        resModel: "partner",
        resId: 1,
    });
    await animationFrame();
    const form = currentView();
    expect(form.config.viewType).toBe("form");
    expect(getService("active_view").has(form)).toBe(true);
    close();
    await animationFrame();
    expect(currentView().config.viewType).toBe("list");
    expect(getService("active_view").has(form)).toBe(false);
});

test("nothing is current once the view is gone", async () => {
    await mountWebClient();
    expect(getService("active_view").current).toBe(null);
});

test("applySearchSpec adds filters, periods, group-bys and field searches", async () => {
    mockDate("2019-07-31T13:43:00");
    await mountView({
        type: "list",
        resModel: "partner",
        arch: `<list><field name="name"/></list>`,
        searchViewArch: SEARCH_ARCH,
    });
    const { searchModel } = currentView();
    await searchModel.applySearchSpec({
        filters: ["companies"],
        dateFilters: [{ name: "date", generatorIds: ["month-1"] }],
        groupBys: ["by_country", { fieldName: "date", interval: "year" }],
        fieldSearches: [{ fieldName: "name", value: "Acme" }],
    });
    await animationFrame();
    expect(getFacetTexts()).toEqual([
        "Companies",
        "Date: June 2019",
        "Country\n>\nDate: Year",
        "Name\nAcme",
    ]);
});

test("applySearchSpec toggles nothing off, and creates an undeclared group-by", async () => {
    await mountView({
        type: "list",
        resModel: "partner",
        arch: `<list><field name="name"/></list>`,
        searchViewArch: SEARCH_ARCH,
    });
    const { searchModel } = currentView();
    await searchModel.applySearchSpec({
        filters: ["companies"],
        groupBys: ["parent_id"],
    });
    await searchModel.applySearchSpec({
        filters: ["companies"],
        groupBys: ["parent_id"],
    });
    await searchModel.applySearchSpec({
        filters: ["no_such_filter"],
        groupBys: ["no_such_field"],
    });
    await animationFrame();
    expect(getFacetTexts()).toEqual(["Companies", "Parent"]);
});
