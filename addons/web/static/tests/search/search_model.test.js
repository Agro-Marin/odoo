// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Deferred, mockDate, mockTimeZone, tick } from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import {
    defineModels,
    fields,
    models,
    mountWithSearch,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { SearchModelEvent } from "@web/core/events";
import { SearchModel } from "@web/search/search_model";
import { SEARCH_MODEL_STATE_VERSION } from "@web/search/search_state";

describe.current.tags("headless");

describe("_notify — the single UPDATE-emission path", () => {
    /** A minimal `this` for `SearchModel.prototype._notify` run in isolation. */
    function notifyStub(overrides = {}) {
        const steps = [];
        return /** @type {any} */ ({
            _steps: steps,
            blockNotification: false,
            _reset() {
                steps.push("reset");
            },
            _reloadSections() {
                steps.push("reloadSections");
                return Promise.resolve();
            },
            trigger(/** @type {any} */ ev) {
                steps.push(`trigger:${ev}`);
            },
            ...overrides,
        });
    }

    test("defaults to reloading the sections before triggering", async () => {
        const model = notifyStub();
        await SearchModel.prototype._notify.call(model);
        expect(model._steps).toEqual(["reset", "reloadSections", "trigger:update"]);
    });

    test("reloadSections:false triggers without re-fetching the sections", () => {
        // The section-refresh path: a caller reacting to a section that already
        // refreshed announces the change without re-triggering that fetch.
        const model = notifyStub();
        SearchModel.prototype._notify.call(model, { reloadSections: false });
        expect(model._steps).toEqual(["reset", "trigger:update"]);
        expect(model._pendingNotification).toBe(undefined);
    });

    test("defers to the pending flag inside a blocked window", () => {
        // A late disk-cache hit landing mid-`_reloadSections` must not trigger
        // UPDATE on its own -- every path funnels through the same batching.
        const model = notifyStub({ blockNotification: true });
        SearchModel.prototype._notify.call(model, { reloadSections: false });
        expect(model._steps).toEqual(["reset"]);
        expect(model._pendingNotification).toBe(true);
    });
});

class TestComponent extends Component {
    static template = xml`<div class="o_test_component"/>`;
    static props = ["*"];
}

async function createSearchModel(searchProps = {}, config = {}) {
    const component = await mountWithSearch(
        TestComponent,
        {
            resModel: "foo",
            searchViewId: false,
            ...searchProps,
        },
        config,
    );
    return component.env.searchModel;
}

function sanitizeSearchItems(/** @type {any} */ model) {
    const searchItems = Object.values(model.searchItems);
    return searchItems.map((searchItem) => {
        const copy = Object.assign({}, searchItem);
        delete copy.groupId;
        delete copy.groupNumber;
        delete copy.id;
        return copy;
    });
}

class Foo extends models.Model {
    name = fields.Char();
    foo = fields.Char({ default: "My little Foo Value" });
    date_field = fields.Date({ string: "Date" });
    float_field = fields.Float({ string: "Float" });
    bar = fields.Many2one({ relation: "partner" });
    properties = fields.Properties({
        definition_record: "bar",
        definition_record_field: "child_properties",
    });
}

class Partner extends models.Model {
    foo = fields.Char();
    bar = fields.Boolean();
    int_field = fields.Integer({ string: "Int Field", aggregator: "sum" });
    company_id = fields.Many2one({ string: "res.company", relation: "res.company" });
    company_ids = fields.Many2many({ string: "Companies", relation: "res.company" });
    category_id = fields.Many2one({ string: "category", relation: "category" });
    state = fields.Selection({
        selection: [
            ["abc", "ABC"],
            ["def", "DEF"],
            ["ghi", "GHI"],
        ],
    });

    _records = [
        {
            id: 1,
            bar: true,
            foo: "yop",
            int_field: 1,
            company_ids: [3],
            company_id: 3,
            state: "abc",
            category_id: 6,
        },
        {
            id: 2,
            bar: true,
            foo: "blip",
            int_field: 2,
            company_ids: [3],
            company_id: 5,
            state: "def",
            category_id: 7,
        },
        {
            id: 3,
            bar: true,
            foo: "gnap",
            int_field: 4,
            company_ids: [],
            company_id: 3,
            state: "ghi",
            category_id: 7,
        },
        {
            id: 4,
            bar: false,
            foo: "blip",
            int_field: 8,
            company_ids: [5],
            company_id: 5,
            state: "ghi",
            category_id: 7,
        },
    ];
}

class Company extends models.Model {
    _name = "res.company";

    name = fields.Char();
    parent_id = fields.Many2one({ string: "Parent company", relation: "res.company" });
    category_id = fields.Many2one({ string: "Category", relation: "category" });

    _records = [
        { id: 3, name: "asustek", category_id: 6 },
        { id: 5, name: "agrolait", category_id: 7 },
    ];
}

class Category extends models.Model {
    name = fields.Char({ string: "Category Name" });

    _records = [
        { id: 6, name: "gold" },
        { id: 7, name: "silver" },
    ];
}

defineModels([Foo, Partner, Company, Category]);

test("parsing empty arch", async () => {
    const model = await createSearchModel();
    expect(sanitizeSearchItems(model)).toEqual([]);
});

test("parsing one field tag", async () => {
    const model = await createSearchModel({
        searchViewArch: `<search><field name="bar"/></search>`,
    });
    expect(sanitizeSearchItems(model)).toEqual([
        {
            description: "Bar",
            fieldName: "bar",
            fieldType: "many2one",
            type: "field",
        },
    ]);
});

test("parsing one separator tag", async () => {
    const model = await createSearchModel({
        searchViewArch: `<search><separator/></search>`,
    });
    expect(sanitizeSearchItems(model)).toEqual([]);
});

test("parsing one separator tag and one field tag", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <separator/>
                <field name="bar"/>
            </search>
        `,
    });
    expect(sanitizeSearchItems(model)).toEqual([
        {
            description: "Bar",
            fieldName: "bar",
            fieldType: "many2one",
            type: "field",
        },
    ]);
});

test("parsing one filter tag", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <filter name="filter" string="Hello" domain="[]"/>
            </search>
        `,
    });
    expect(sanitizeSearchItems(model)).toEqual([
        {
            description: "Hello",
            domain: "[]",
            name: "filter",
            type: "filter",
        },
    ]);
});

test("parsing one filter tag with default_period date attribute", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <filter name="date_filter" string="Date" date="date_field" default_period="year,year-1"/>
            </search>
        `,
    });
    expect(sanitizeSearchItems(model)).toEqual([
        {
            defaultGeneratorIds: ["year", "year-1"],
            description: "Date",
            domain: "[]",
            fieldName: "date_field",
            fieldType: "date",
            type: "dateFilter",
            name: "date_filter",
            optionsParams: {
                customOptions: [],
                endMonth: 0,
                endYear: 0,
                startMonth: -2,
                startYear: -2,
            },
        },
    ]);
});

test("parsing date filter with start_month, end_month, start_year, end_year attributes", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <filter
                    name="date_filter"
                    string="Date"
                    date="date_field"
                    start_month="-4"
                    end_month="-1"
                    start_year="-1"
                    end_year="3"
                />
            </search>
        `,
    });
    expect(sanitizeSearchItems(model)).toEqual([
        {
            defaultGeneratorIds: ["month-1"],
            description: "Date",
            domain: "[]",
            fieldName: "date_field",
            fieldType: "date",
            type: "dateFilter",
            name: "date_filter",
            optionsParams: {
                customOptions: [],
                endMonth: -1,
                endYear: 3,
                startMonth: -4,
                startYear: -1,
            },
        },
    ]);
});

test("parsing date filter with custom options", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <filter name="date_filter" string="Date" date="date_field">
                    <filter name="birthday_today" string="Today" domain="[('date_field', '=', context_today().strftime('%Y-%m-%d'))]"/>
                    <filter name="birthday_future" string="Future" domain="[('date_field', '>=', context_today().strftime('%Y-%m-%d'))]"/>
                </filter>
            </search>
        `,
    });
    expect(sanitizeSearchItems(model)).toEqual([
        {
            defaultGeneratorIds: ["month"],
            description: "Date",
            domain: "[]",
            fieldName: "date_field",
            fieldType: "date",
            name: "date_filter",
            optionsParams: {
                customOptions: [
                    {
                        id: "custom_birthday_today",
                        description: "Today",
                        domain: "[('date_field', '=', context_today().strftime('%Y-%m-%d'))]",
                        type: "dateOption",
                    },
                    {
                        id: "custom_birthday_future",
                        description: "Future",
                        domain: "[('date_field', '>=', context_today().strftime('%Y-%m-%d'))]",
                        type: "dateOption",
                    },
                ],
                endMonth: 0,
                endYear: 0,
                startMonth: -2,
                startYear: -2,
            },
            type: "dateFilter",
        },
    ]);
});

test("parsing one filter tag with date attribute ", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <filter name="date_filter" string="Date" date="date_field"/>
            </search>
        `,
    });
    expect(sanitizeSearchItems(model)).toEqual([
        {
            defaultGeneratorIds: ["month"],
            description: "Date",
            domain: "[]",
            fieldName: "date_field",
            fieldType: "date",
            name: "date_filter",
            optionsParams: {
                customOptions: [],
                endMonth: 0,
                endYear: 0,
                startMonth: -2,
                startYear: -2,
            },
            type: "dateFilter",
        },
    ]);
});

test("parsing one groupBy tag", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <filter name="groupby" string="Hi" context="{ 'group_by': 'date_field:day'}"/>
            </search>
        `,
    });
    expect(sanitizeSearchItems(model)).toEqual([
        {
            defaultIntervalId: "day",
            description: "Hi",
            fieldName: "date_field",
            fieldType: "date",
            name: "groupby",
            type: "dateGroupBy",
        },
    ]);
});

test("parsing two filter tags", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <filter name="filter_1" string="Hello One" domain="[]"/>
                <filter name="filter_2" string="Hello Two" domain="[('bar', '=', 3)]"/>
            </search>
        `,
    });
    expect(sanitizeSearchItems(model)).toEqual([
        {
            description: "Hello One",
            domain: "[]",
            name: "filter_1",
            type: "filter",
        },
        {
            description: "Hello Two",
            domain: "[('bar', '=', 3)]",
            name: "filter_2",
            type: "filter",
        },
    ]);
});

test("parsing two filter tags separated by a separator", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <filter name="filter_1" string="Hello One" domain="[]"/>
                <separator/>
                <filter name="filter_2" string="Hello Two" domain="[('bar', '=', 3)]"/>
            </search>
        `,
    });
    expect(sanitizeSearchItems(model)).toEqual([
        {
            description: "Hello One",
            domain: "[]",
            name: "filter_1",
            type: "filter",
        },
        {
            description: "Hello Two",
            domain: "[('bar', '=', 3)]",
            name: "filter_2",
            type: "filter",
        },
    ]);
});

test("parsing one filter tag and one field", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <filter name="filter" string="Hello" domain="[]"/>
                <field name="bar"/>
            </search>
        `,
    });
    expect(sanitizeSearchItems(model)).toEqual([
        {
            description: "Hello",
            domain: "[]",
            name: "filter",
            type: "filter",
        },
        {
            description: "Bar",
            fieldName: "bar",
            fieldType: "many2one",
            type: "field",
        },
    ]);
});

test("parsing two field tags", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <field name="foo"/>
                <field name="bar"/>
            </search>
        `,
    });
    expect(sanitizeSearchItems(model)).toEqual([
        {
            description: "Foo",
            fieldName: "foo",
            fieldType: "char",
            type: "field",
        },
        {
            description: "Bar",
            fieldName: "bar",
            fieldType: "many2one",
            type: "field",
        },
    ]);
});

test("parsing a searchpanel tag", async () => {
    const model = await createSearchModel(
        {
            searchViewArch: `
                <search>
                    <searchpanel/>
                </search>
            `,
        },
        { viewType: "kanban" },
    );
    expect(model.getSections()).toEqual([]);
});

test("parsing a searchpanel field select one", async () => {
    const model = await createSearchModel(
        {
            searchViewArch: `
                <search>
                    <searchpanel>
                        <field name="company_id"/>
                    </searchpanel>
                </search>
            `,
            resModel: "partner",
        },
        { viewType: "kanban" },
    );
    const sections = model.getSections();
    for (const section of sections) {
        section.values = [...section.values];
    }
    expect(sections).toEqual([
        {
            activeValueId: false,
            color: null,
            description: "res.company",
            depth: 0,
            empty: false,
            enableCounters: false,
            expand: false,
            fieldName: "company_id",
            hierarchize: true,
            icon: "fa-solid fa-folder",
            id: 1,
            limit: 200,
            parentField: "parent_id",
            rootIds: [false, 3, 5],
            type: "category",
            values: [
                [
                    false,
                    {
                        bold: true,
                        childrenIds: [],
                        display_name: "All",
                        id: false,
                        parentId: false,
                    },
                ],
                [
                    3,
                    {
                        childrenIds: [],
                        display_name: "asustek",
                        id: 3,
                        parentId: false,
                        parent_id: false,
                    },
                ],
                [
                    5,
                    {
                        childrenIds: [],
                        display_name: "agrolait",
                        id: 5,
                        parentId: false,
                        parent_id: false,
                    },
                ],
            ],
        },
    ]);
});

test("parsing a searchpanel field select multi", async () => {
    const model = await createSearchModel(
        {
            searchViewArch: `
                <search>
                    <searchpanel>
                        <field name="company_id" select="multi"/>
                    </searchpanel>
                </search>
            `,
            resModel: "partner",
        },
        { viewType: "kanban" },
    );
    const sections = model.getSections();
    for (const section of sections) {
        section.values = [...section.values];
    }
    expect(sections).toEqual([
        {
            color: null,
            description: "res.company",
            domain: "[]",
            empty: false,
            enableCounters: false,
            expand: false,
            fieldName: "company_id",
            groupBy: null,
            icon: "fa-solid fa-filter",
            id: 1,
            limit: 200,
            type: "filter",
            values: [
                [
                    3,
                    {
                        checked: false,
                        display_name: "asustek",
                        id: 3,
                    },
                ],
                [
                    5,
                    {
                        checked: false,
                        display_name: "agrolait",
                        id: 5,
                    },
                ],
            ],
        },
    ]);
});

test("parsing a filter and a dateFilter", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <filter name="filter" string="Filter" domain="[['foo', '=', 'a']]"/>
                <filter name="date_filter" string="Date" date="date_field"/>
            </search>
        `,
    });
    const groupNumbers = model
        .getSearchItems(() => true)
        .map((/** @type {any} */ i) => i.groupNumber);
    expect(groupNumbers).toEqual([1, 1]);
});

test("parsing a groupBy and a dateGroupBy", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <filter name="group_by" context="{ 'group_by': 'foo'}"/>
                <filter name="date_groupBy" string="DateGroupBy" context="{'group_by': 'date_field:day'}"/>
            </search>
        `,
    });
    const groupNumbers = model
        .getSearchItems(() => true)
        .map((/** @type {any} */ i) => i.groupNumber);
    expect(groupNumbers).toEqual([1, 1]);
});

test("parsing a filter and a groupBy", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <filter name="filter" string="Filter" domain="[['foo', '=', 'a']]"/>
                <filter name="group_by" context="{ 'group_by': 'foo'}"/>
            </search>
        `,
    });
    const groupNumbers = model
        .getSearchItems(() => true)
        .map((/** @type {any} */ i) => i.groupNumber);
    expect(groupNumbers).toEqual([1, 2]);
});

test("parsing a groupBy and a filter", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <filter name="group_by" context="{ 'group_by': 'foo'}"/>
                <filter name="filter" string="Filter" domain="[['foo', '=', 'a']]"/>
            </search>
        `,
    });
    const groupNumbers = model
        .getSearchItems(() => true)
        .map((/** @type {any} */ i) => i.groupNumber);
    // Arch order, not creation order: the parser collects every group-by into
    // one pregroup and appends it last, so ordering by id alone reported this
    // group-by after the filter that follows it in the arch.
    expect(groupNumbers).toEqual([1, 2]);
});

test("process search default group by", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <filter name="group_by" context="{ 'group_by': 'foo'}"/>
            </search>
        `,
        context: { search_default_group_by: 14 },
    });
    expect(sanitizeSearchItems(model)).toEqual([
        {
            defaultRank: 14,
            description: "Foo",
            fieldName: "foo",
            fieldType: "char",
            name: "group_by",
            type: "groupBy",
            isDefault: true,
        },
    ]);
});

test("process and toggle a field with a context to evaluate", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <field name="foo" context="{ 'a': self }"/>
            </search>
        `,
    });
    expect(sanitizeSearchItems(model)).toEqual([
        {
            context: "{ 'a': self }",
            description: "Foo",
            fieldName: "foo",
            fieldType: "char",
            type: "field",
        },
    ]);
    model.addAutoCompletionValues(1, { label: "7", operator: "=", value: 7 });
    expect(model.context).toEqual({
        a: [7],
        lang: "en",
        tz: "taht",
        uid: 7,
        allowed_company_ids: [1],
    });
});

test("process favorite filters", async () => {
    const model = await createSearchModel({
        irFilters: [
            {
                user_ids: [2],
                name: "Sorted filter",
                id: 5,
                context: `{"group_by":["foo","bar"]}`,
                sort: '["foo", "-bar"]',
                domain: "[('user_id', '=', uid)]",
                is_default: false,
                model_id: "res.partner",
                action_id: false,
            },
        ],
    });
    expect(sanitizeSearchItems(model)).toEqual([
        {
            context: {},
            description: "Sorted filter",
            domain: "[('user_id', '=', uid)]",
            groupBys: ["foo", "bar"],
            isInvalid: false,
            orderBy: [
                {
                    asc: true,
                    name: "foo",
                },
                {
                    asc: false,
                    name: "bar",
                },
            ],
            removable: true,
            serverSideId: 5,
            type: "favorite",
            userIds: [2],
        },
    ]);
});

test("favorite group_bys naming removed fields are screened at import", async () => {
    const warnings = [];
    const originalWarn = console.warn;
    console.warn = (...args) => warnings.push(args.join(" "));
    let model;
    try {
        model = await createSearchModel({
            irFilters: [
                {
                    user_ids: [],
                    name: "Ghost grouping",
                    id: 5,
                    context: `{"group_by": ["ghost_field", "name", "date_field:month"]}`,
                    sort: "[]",
                    domain: "[]",
                    is_default: true,
                    model_id: "foo",
                    action_id: false,
                },
            ],
        });
    } finally {
        console.warn = originalWarn;
    }
    expect(warnings.length).toBe(1);
    expect(warnings[0]).toInclude("ghost_field");

    const favorite = Object.values(model.searchItems).find(
        (item) => item.type === "favorite",
    );
    expect(favorite.groupBys).toEqual(["name", "date_field:month"]);
    expect(model.groupBy).toEqual(["name", "date_field:month"]);
});

test("process dynamic filters", async () => {
    const model = await createSearchModel({
        dynamicFilters: [
            {
                description: "Quick search",
                domain: [["id", "in", [1, 3, 4]]],
            },
        ],
    });
    expect(sanitizeSearchItems(model)).toEqual([
        {
            description: "Quick search",
            domain: [["id", "in", [1, 3, 4]]],
            isDefault: true,
            type: "filter",
        },
    ]);
});

test("process a dynamic filter with a isDefault key to false", async () => {
    const model = await createSearchModel({
        dynamicFilters: [
            {
                description: "Quick search",
                domain: [],
                is_default: false,
            },
        ],
    });
    expect(sanitizeSearchItems(model)).toEqual([
        {
            description: "Quick search",
            domain: [],
            isDefault: false,
            type: "filter",
        },
    ]);
});

test("toggle a filter", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <filter name="filter" string="Filter" domain="[['foo', '=', 'a']]"/>
            </search>
        `,
    });
    const filterId = Object.keys(model.searchItems).map((key) => Number(key))[0];
    expect(model.domain).toEqual([]);
    model.toggleSearchItem(filterId);
    expect(model.domain).toEqual([["foo", "=", "a"]]);
    model.toggleSearchItem(filterId);
    expect(model.domain).toEqual([]);
});

test("toggle a date filter", async () => {
    mockDate("2019-01-06T15:00:00");
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <filter name="date_filter" date="date_field" string="DateFilter"/>
            </search>
        `,
    });
    const filterId = Object.keys(model.searchItems).map((key) => Number(key))[0];
    model.toggleDateFilter(filterId);
    expect(model.domain).toEqual([
        "&",
        ["date_field", ">=", "2019-01-01"],
        ["date_field", "<=", "2019-01-31"],
    ]);
    model.toggleDateFilter(filterId, "first_quarter");
    expect(model.domain).toEqual([
        "|",
        "&",
        ["date_field", ">=", "2019-01-01"],
        ["date_field", "<=", "2019-01-31"],
        "&",
        ["date_field", ">=", "2019-01-01"],
        ["date_field", "<=", "2019-03-31"],
    ]);
    model.toggleDateFilter(filterId, "year");
    expect(model.domain).toEqual([]);
});

test("toggle a custom option in a date filter", async () => {
    mockDate("2019-01-06T15:00:00");
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <filter name="date_filter" date="date_field" string="DateFilter">
                    <filter name="today" string="Today" domain="[('date_field', '=', context_today().strftime('%Y-%m-%d'))]"/>
                </filter>
            </search>
        `,
    });
    const filterId = Object.keys(model.searchItems).map((key) => Number(key))[0];
    model.toggleDateFilter(filterId);
    expect(model.domain).toEqual([
        "&",
        ["date_field", ">=", "2019-01-01"],
        ["date_field", "<=", "2019-01-31"],
    ]);
    model.toggleDateFilter(filterId, "custom_today");
    expect(model.domain).toEqual([["date_field", "=", "2019-01-06"]]);
});

test("toggle a date filter with a domain", async () => {
    mockDate("2019-01-06T15:00:00");
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <filter name="date_filter" date="date_field" string="DateFilter" domain="[('float_field', '>=', '0')]"/>
            </search>
        `,
    });
    const filterId = Object.keys(model.searchItems).map((key) => Number(key))[0];
    expect(model.domain).toEqual([]);
    model.toggleDateFilter(filterId);
    expect(model.domain).toEqual([
        "&",
        "&",
        ["date_field", ">=", "2019-01-01"],
        ["date_field", "<=", "2019-01-31"],
        ["float_field", ">=", "0"],
    ]);
});

test("toggle a custom option in a date filter with a domain", async () => {
    mockDate("2019-01-06T15:00:00");
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <filter name="date_filter" date="date_field" string="DateFilter" domain="[('float_field', '>=', '0')]">
                    <filter name="today" string="Today" domain="[('date_field', '=', context_today().strftime('%Y-%m-%d'))]"/>
                </filter>
            </search>
        `,
    });
    const filterId = Object.keys(model.searchItems).map((key) => Number(key))[0];
    model.toggleDateFilter(filterId, "custom_today");
    expect(model.domain).toEqual([
        "&",
        ["date_field", "=", "2019-01-06"],
        ["float_field", ">=", "0"],
    ]);
});

test("toggle a groupBy", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <filter name="groupBy" string="GroupBy" context="{'group_by': 'foo'}"/>
            </search>
        `,
    });
    const filterId = Object.keys(model.searchItems).map((key) => Number(key))[0];
    expect(model.groupBy).toEqual([]);
    model.toggleSearchItem(filterId);
    expect(model.groupBy).toEqual(["foo"]);
    model.toggleSearchItem(filterId);
    expect(model.groupBy).toEqual([]);
});

test("toggle a date groupBy", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <filter name="date_groupBy" string="DateGroupBy" context="{'group_by': 'date_field:day'}"/>
            </search>
        `,
    });
    const filterId = Object.keys(model.searchItems).map((key) => Number(key))[0];
    expect(model.groupBy).toEqual([]);
    model.toggleDateGroupBy(filterId);
    expect(model.groupBy).toEqual(["date_field:day"]);
    model.toggleDateGroupBy(filterId, "week");
    expect(model.groupBy).toEqual(["date_field:week", "date_field:day"]);
    model.toggleDateGroupBy(filterId);
    expect(model.groupBy).toEqual(["date_field:week"]);
    model.toggleDateGroupBy(filterId, "week");
    expect(model.groupBy).toEqual([]);
});

test("create a new groupBy", async () => {
    const model = await createSearchModel();
    model.createNewGroupBy("foo");
    expect(sanitizeSearchItems(model)).toEqual([
        {
            custom: true,
            description: "Foo",
            fieldName: "foo",
            fieldType: "char",
            type: "groupBy",
        },
    ]);
    expect(model.groupBy).toEqual(["foo"]);
});

test("create a new dateGroupBy", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <filter name="foo" string="Foo" context="{'group_by': 'foo'}"/>
            </search>
        `,
    });
    model.createNewGroupBy("date_field");
    expect(sanitizeSearchItems(model)).toEqual([
        {
            description: "Foo",
            fieldName: "foo",
            fieldType: "char",
            name: "foo",
            type: "groupBy",
        },
        {
            custom: true,
            defaultIntervalId: "month",
            description: "Date",
            fieldName: "date_field",
            fieldType: "date",
            type: "dateGroupBy",
        },
    ]);
    expect(model.groupBy).toEqual(["date_field:month"]);
});

test("dynamic domains evaluation", async () => {
    mockDate("2021-09-17T10:00:00");
    mockTimeZone(2);

    const searchViewArch = `
        <search>
            <filter name="filter_0" domain="[('datetime', '=', (datetime.datetime.combine(context_today(), datetime.time(0,0,0)).to_utc()))]"/>
            <filter name="filter_1" domain="[('date', '=',  context_today() + relativedelta(days=-365))]"/>
            <filter name="filter_2" domain="[('create_date', '&gt;', (context_today() - datetime.timedelta(days=1)).strftime('%Y-%m-%d'))]"/>
            <filter name="filter_3" domain="[('date_deadline', '&lt;', current_date)]"/>
        </search>
    `;

    const evaluatedDomains = [
        [["datetime", "=", "2021-09-16 22:00:00"]],
        [["date", "=", "2020-09-17"]],
        [["create_date", ">", "2021-09-16"]],
        [["date_deadline", "<", "2021-09-17"]],
    ];

    const model = await createSearchModel({
        searchViewArch,
    });
    for (let i = 0; i < evaluatedDomains.length; i++) {
        model.toggleSearchItem(i + 1);
        expect(model.domain).toEqual(evaluatedDomains[i]);
        model.toggleSearchItem(i + 1);
    }
});

test("dynamic domains evaluation using global context", async () => {
    const searchViewArch = `
        <search>
            <filter name="filter" domain="[('date_deadline', '&lt;', context.get('my_date'))]"/>
        </search>
    `;

    const model = await createSearchModel({
        searchViewArch,
        context: {
            my_date: "2021-09-17",
        },
    });

    model.toggleSearchItem(1);
    expect(model.domain).toEqual([["date_deadline", "<", "2021-09-17"]]);
});

test("field tags with invisible attribute", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <field name="foo" invisible="context.get('abc')"/>
                <field name="bar" invisible="context.get('def')"/>
                <field name="float_field" invisible="1"/>
            </search>
        `,
        context: { abc: true },
    });
    const fields = model
        .getSearchItems((/** @type {any} */ f) => f.type === "field")
        .map((/** @type {any} */ item) => item.fieldName);
    expect(fields).toEqual(["bar"]);
});

test("filter tags with invisible attribute", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <filter name="filter1" string="Invisible ABC" domain="[]" invisible="context.get('abc')"/>
                <filter name="filter2" string="Invisible DEF" domain="[]" invisible="context.get('def')"/>
                <filter name="filter3" string="Always invisible" domain="[]" invisible="1"/>
            </search>
        `,
        context: { abc: true },
    });
    const filters = model
        .getSearchItems((/** @type {any} */ item) =>
            ["filter", "dateFilter"].includes(item.type),
        )
        .map((/** @type {any} */ item) => item.name);
    expect(filters).toEqual(["filter2"]);
});

test("no search items created for search panel sections", async () => {
    const model = await createSearchModel(
        {
            searchViewArch: `
                <search>
                    <searchpanel>
                        <field name="company_id"/>
                        <field name="company_id" select="multi"/>
                    </searchpanel>
                </search>
            `,
            resModel: "partner",
        },
        { viewType: "kanban" },
    );
    const sections = model.getSections();
    expect(sections).toHaveLength(2);
    expect(sanitizeSearchItems(model)).toEqual([]);
});

test("a field of type 'properties' should not be accepted as a search_default", async () => {
    const searchViewArch = `
        <search>
            <field name="properties"/>
        </search>
    `;

    const model = await createSearchModel({
        searchViewArch,
        context: {
            search_default_properties: true,
        },
    });
    expect(sanitizeSearchItems(model)).toEqual([
        {
            description: "Properties",
            fieldName: "properties",
            fieldType: "properties",
            type: "field",
        },
    ]);
});

test("allow filtering based on extra keys in getSearchItems", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <filter name="filter_1" string="Filter 1" domain="[['foo', '=', 'a']]"/>
                <filter name="filter_2" string="Filter 2" domain="[['foo', '=', 'b']]"/>
            </search>
        `,
        context: {
            search_default_filter_1: true,
        },
    });
    const items = model.getSearchItems((/** @type {any} */ i) => i.isActive);
    expect(items).toHaveLength(1);
    expect(items[0].name).toBe("filter_1");
});

test("exportState returns a snapshot decoupled from the live model", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <filter name="filter_1" string="Filter 1" domain="[['foo', '=', 'a']]"/>
            </search>
        `,
        context: {
            search_default_filter_1: true,
        },
    });

    const state = model.exportState();

    expect(state.query).not.toBe(model.query);
    const queryLength = state.query.length;
    expect(queryLength).toBeGreaterThan(0);
    model.query.push({ searchItemId: -1 });
    expect(state.query).toHaveLength(queryLength);

    const someId = Object.keys(model.searchItems)[0];
    expect(someId).not.toBe(undefined);
    model.searchItems[someId].__probe = "MUTATED";
    expect(state.searchItems[someId].__probe).toBe(undefined);
});

test("exportState stamps the schema version", async () => {
    const model = await createSearchModel({
        searchViewArch: `<search/>`,
    });
    expect(model.exportState().version).toBe(SEARCH_MODEL_STATE_VERSION);
});

test("a versionless legacy state imports identically to today's shape", async () => {
    const searchViewArch = `
        <search>
            <filter name="filter_1" string="Filter 1" domain="[['foo', '=', 'a']]"/>
        </search>
    `;
    const model = await createSearchModel({
        searchViewArch,
        context: { search_default_filter_1: true },
    });

    // What a pre-versioning build serialized: the same state minus the keys
    // that joined the schema with the version field.
    const legacy = JSON.parse(JSON.stringify(model.exportState()));
    delete legacy.version;
    delete legacy.searchDomain;
    delete legacy.propertySearchViewFields;

    const restored = await createSearchModel({
        searchViewArch,
        globalState: { searchModel: JSON.stringify(legacy) },
    });
    expect(restored.query).toEqual(model.query);
    expect(JSON.parse(JSON.stringify(restored.searchItems))).toEqual(
        JSON.parse(JSON.stringify(model.searchItems)),
    );
    expect(restored.domain).toEqual([["foo", "=", "a"]]);
});

test("a state of an unknown future version warns and imports best-effort", async () => {
    patchWithCleanup(console, {
        warn: (msg) => {
            if (String(msg).startsWith("[search] importing a search state")) {
                expect.step("warn");
            }
        },
    });
    const searchViewArch = `
        <search>
            <filter name="filter_1" string="Filter 1" domain="[['foo', '=', 'a']]"/>
        </search>
    `;
    const model = await createSearchModel({
        searchViewArch,
        context: { search_default_filter_1: true },
    });
    const state = model.exportState();
    state.version = SEARCH_MODEL_STATE_VERSION + 1;
    state.keyFromTheFuture = { anything: true };

    const restored = await createSearchModel({
        searchViewArch,
        globalState: { searchModel: JSON.stringify(state) },
    });
    expect.verifySteps(["warn"]);
    // The known keys still land: refusing the import would throw away the
    // user's search on every cross-build restore.
    expect(restored.query).toEqual(model.query);
});

test("property-derived searchViewFields entries survive an export/import cycle", async () => {
    const searchViewArch = `
        <search>
            <field name="properties"/>
        </search>
    `;
    const definitions = [{ name: "my_char", string: "My Char", type: "char" }];
    patchWithCleanup(SearchModel.prototype, {
        async _fetchPropertiesDefinition() {
            return [
                {
                    definitionRecordId: 1,
                    definitionRecordName: "Parent",
                    definitions,
                },
            ];
        },
    });
    const model = await createSearchModel({ searchViewArch });
    await model.fillSearchViewItemsProperty();
    const item = Object.values(model.searchItems).find(
        (i) => i.fieldName === "properties.my_char",
    );
    expect(item).not.toBe(undefined);
    model.toggleSearchItem(item.id);
    expect(model.groupBy).toEqual(["properties.my_char"]);

    const restored = await createSearchModel({
        searchViewArch,
        globalState: { searchModel: JSON.stringify(model.exportState()) },
    });

    // The group-by item survived the restore AND resolves its field again:
    // the property-derived entry is not part of the reloaded view description,
    // so without the state carrying it the item pointed at nothing.
    expect(restored.groupBy).toEqual(["properties.my_char"]);
    const restoredField = restored.searchViewFields["properties.my_char"];
    expect(restoredField.string).toBe("My Char");
    // The parent reference is re-aliased onto the live parent field.
    expect(restoredField.relatedPropertyField).toBe(
        restored.searchViewFields.properties,
    );
});

test("fillSearchViewItemsProperty refetches definitions on each sequential call", async () => {
    // Deliberately NOT memoised across calls: definitions live on the parent
    // record and change under us, and the only caller is one dropdown open.
    // Concurrent calls still share one fetch — see the next test.
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <field name="properties"/>
            </search>
        `,
    });

    const fetchedFields = [];
    model._fetchPropertiesDefinition = (
        /** @type {any} */ resModel,
        /** @type {any} */ fieldName,
    ) => {
        fetchedFields.push(fieldName);
        return Promise.resolve([]);
    };

    await model.fillSearchViewItemsProperty();
    await model.fillSearchViewItemsProperty();
    await model.fillSearchViewItemsProperty();

    expect(fetchedFields).toEqual(["properties", "properties", "properties"]);
});

test("a property added on the parent record reaches the group-by items", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <field name="properties"/>
            </search>
        `,
    });

    let definitions = [{ name: "my_char", string: "My Char", type: "char" }];
    model._fetchPropertiesDefinition = async () => [
        { definitionRecordId: 1, definitionRecordName: "Parent", definitions },
    ];
    const isPropertyGroupBy = (/** @type {any} */ item) =>
        item.isProperty && ["groupBy", "dateGroupBy"].includes(item.type);

    await model.fillSearchViewItemsProperty();
    expect(model.getSearchItems(isPropertyGroupBy)).toHaveLength(1);

    definitions = [
        ...definitions,
        { name: "my_int", string: "My Int", type: "integer" },
    ];
    await model.fillSearchViewItemsProperty();
    expect(model.getSearchItems(isPropertyGroupBy)).toHaveLength(2);
});

test("concurrent fillSearchViewItemsProperty calls both see the loaded items", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <field name="properties"/>
            </search>
        `,
    });

    const def = new Deferred();
    let fetchCount = 0;
    model._fetchPropertiesDefinition = async () => {
        fetchCount++;
        await def;
        return [
            {
                definitionRecordId: 1,
                definitionRecordName: "Parent",
                definitions: [{ name: "my_char", string: "My Char", type: "char" }],
            },
        ];
    };

    const isPropertyGroupBy = (/** @type {any} */ item) =>
        item.isProperty && ["groupBy", "dateGroupBy"].includes(item.type);

    const firstFill = model.fillSearchViewItemsProperty();
    const secondFill = model.fillSearchViewItemsProperty();

    let secondSettled = false;
    secondFill.then(() => {
        secondSettled = true;
    });
    await tick();
    expect(secondSettled).toBe(false);
    expect(model.getSearchItems(isPropertyGroupBy)).toHaveLength(0);

    def.resolve();
    await secondFill;
    expect(model.getSearchItems(isPropertyGroupBy)).toHaveLength(1);

    await firstFill;
    expect(fetchCount).toBe(1);
});

test("a query mutation racing an in-flight reload still notifies", async () => {
    // `reload` opens a notification-blocking window around `_reloadSections`;
    // a toggle landing inside it used to set `_pendingNotification` with no
    // consumer left to drain it, so the view kept the pre-toggle domain.
    const def = new Deferred();
    onRpc("search_panel_select_range", async () => {
        await def;
        return { parent_field: false, values: [] };
    });
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <filter name="filter" string="Filter" domain="[('foo', '=', 'a')]"/>
                <searchpanel>
                    <field name="bar" enable_counters="1"/>
                </searchpanel>
            </search>`,
    });

    let updates = 0;
    model.addEventListener(SearchModelEvent.UPDATE, () => updates++);

    const reloadProm = model.reload({ domain: [["id", "=", 1]] });
    // `_reloadSections` runs its body in a Mutex microtask: wait for the
    // blocking window to actually be open before mutating the query.
    await tick();
    expect(model.blockNotification).toBe(true);

    const filterId = Object.values(model.searchItems).find(
        (item) => item.type === "filter",
    ).id;
    model.toggleSearchItem(filterId);
    def.resolve();
    await reloadProm;
    await tick();

    expect(updates).toBe(1);
    expect(model.domain).toEqual(["&", ["id", "=", 1], ["foo", "=", "a"]]);
});

test("a scalar searchpanel default on a multi-select field is accepted", async () => {
    onRpc("search_panel_select_multi_range", () => ({
        values: [{ id: 3, display_name: "asustek", count: 1 }],
    }));
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <searchpanel>
                    <field name="bar" select="multi"/>
                </searchpanel>
            </search>`,
        context: { searchpanel_default_bar: 3 },
    });
    expect(model.domain).toEqual([["bar", "in", [3]]]);
});

describe("memoized getter contracts", () => {
    test("groupBy hands out a fresh array on every access", async () => {
        const model = await createSearchModel({ groupBy: ["foo"] });
        const first = model.groupBy;
        const second = model.groupBy;
        // Consumers park this on reactive models; Owl keys its reactive caches
        // by raw target, so a shared array entangles their subscriptions.
        expect(first).toEqual(second);
        expect(first === second).toBe(false);
    });

    test("orderBy neither aliases nor freezes the caller's array", async () => {
        const callerOrderBy = [{ name: "foo", asc: true }];
        const model = await createSearchModel({ orderBy: callerOrderBy });
        expect(model.orderBy).toEqual(callerOrderBy);
        expect(model.orderBy === callerOrderBy).toBe(false);
        expect(Object.isFrozen(callerOrderBy)).toBe(false);
    });

    test("categories/filters are stable while the sections map is", async () => {
        const model = await createSearchModel({
            searchViewArch: `<search><searchpanel><field name="bar"/></searchpanel></search>`,
        });
        await model.sectionsPromise;
        expect(model.categories === model.categories).toBe(true);
        expect(model.filters === model.filters).toBe(true);
        expect(model.categories.length).toBe(1);
        expect(model.filters.length).toBe(0);
    });
});

test("a property deleted on the parent record stops contributing to the domain", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <field name="properties"/>
            </search>
        `,
    });

    let definitions = [
        { name: "kept", string: "Kept", type: "char" },
        { name: "gone", string: "Gone", type: "char" },
    ];
    model._fetchPropertiesDefinition = async () => [
        { definitionRecordId: 1, definitionRecordName: "Parent", definitions },
    ];
    const propertiesItem = Object.values(model.searchItems).find(
        (item) => item.fieldType === "properties",
    );
    const isFieldProperty = (/** @type {any} */ item) => item.type === "field_property";

    const created = await model.getSearchItemsProperties(propertiesItem);
    expect(created).toHaveLength(2);

    const gone = created.find(
        (/** @type {any} */ i) => i.propertyFieldDefinition.name === "gone",
    );
    model.addAutoCompletionValues(gone.id, {
        label: "x",
        operator: "=",
        value: "x",
    });
    expect(JSON.stringify(model.domain)).toInclude("properties.gone");

    definitions = [definitions[0]];
    await model.getSearchItemsProperties(propertiesItem);

    expect(model.getSearchItems(isFieldProperty)).toHaveLength(1);
    expect(JSON.stringify(model.domain)).not.toInclude("properties.gone");
    expect(model.query.some((/** @type {any} */ q) => q.searchItemId === gone.id)).toBe(
        false,
    );
});

test("an active property group-by is retired when its definition is deleted", async () => {
    // The item used to be re-typed to "group_by_property_deleted" and left in
    // the query: nothing renders that type, so it disappeared from the Group By
    // menu while the search bar kept a chip with no icon, no colour and no
    // label for it, and the memos the view reads were never invalidated.
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <field name="properties"/>
            </search>
        `,
    });
    let definitions = [{ name: "p1", string: "P1", type: "char" }];
    model._fetchPropertiesDefinition = async () => [
        { definitionRecordId: 1, definitionRecordName: "Parent", definitions },
    ];
    await model.fillSearchViewItemsProperty();

    const item = Object.values(model.searchItems).find((i) => i.isProperty);
    await model.toggleSearchItem(item.id);
    expect(model.groupBy).toEqual(["properties.p1"]);
    expect(model.facets).toHaveLength(1);

    definitions = [];
    await model.fillSearchViewItemsProperty();

    expect(model.searchItems[item.id]).toBe(undefined);
    expect(model.query).toEqual([]);
    expect(model.groupBy).toEqual([]);
    expect(model.facets).toEqual([]);
});

test("a definition record dropping out entirely retires its group-bys", async () => {
    // The retiring pass used to key on definitionRecordId taken from the
    // result, so a record that stopped contributing definitions was never
    // considered at all.
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <field name="properties"/>
            </search>
        `,
    });
    let result = [
        {
            definitionRecordId: 1,
            definitionRecordName: "Parent",
            definitions: [{ name: "p1", string: "P1", type: "char" }],
        },
    ];
    model._fetchPropertiesDefinition = async () => result;
    await model.fillSearchViewItemsProperty();

    const item = Object.values(model.searchItems).find((i) => i.isProperty);
    await model.toggleSearchItem(item.id);
    expect(model.groupBy).toEqual(["properties.p1"]);

    result = [];
    await model.fillSearchViewItemsProperty();

    expect(model.getSearchItems((/** @type {any} */ i) => i.isProperty)).toEqual([]);
    expect(model.groupBy).toEqual([]);
    expect(model.facets).toEqual([]);
});

test("an untouched property group-by keeps its id across a refresh", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <field name="properties"/>
            </search>
        `,
    });
    model._fetchPropertiesDefinition = async () => [
        {
            definitionRecordId: 1,
            definitionRecordName: "Parent",
            definitions: [
                { name: "p1", string: "P1", type: "char" },
                { name: "p2", string: "P2", type: "char" },
            ],
        },
    ];
    await model.fillSearchViewItemsProperty();
    const idsBefore = model
        .getSearchItems((/** @type {any} */ i) => i.isProperty)
        .map((/** @type {any} */ i) => i.id);

    await model.fillSearchViewItemsProperty();

    expect(
        model
            .getSearchItems((/** @type {any} */ i) => i.isProperty)
            .map((/** @type {any} */ i) => i.id),
    ).toEqual(idsBefore);
});

test("editing the domain of a favorite that group-bys a property", async () => {
    // splitAndAddDomain re-creates the favorite's group-bys as custom ones,
    // which needs field metadata a property only gets once the definitions have
    // been fetched. It used to throw a TypeError out of createNewGroupBy AFTER
    // deactivating the favorite's group, losing the whole search.
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <field name="properties"/>
            </search>
        `,
        irFilters: [
            {
                context: "{'group_by': ['properties.p1']}",
                domain: "[('foo', '=', 'a')]",
                id: 1,
                is_default: true,
                name: "Fav",
                sort: "[]",
                user_ids: [2],
            },
        ],
    });
    model._fetchPropertiesDefinition = async () => [
        {
            definitionRecordId: 1,
            definitionRecordName: "Parent",
            definitions: [{ name: "p1", string: "P1", type: "char" }],
        },
    ];
    expect(model.groupBy).toEqual(["properties.p1"]);
    const facet = model.facets.find((/** @type {any} */ f) => f.type === "favorite");

    await model.splitAndAddDomain(`[("foo", "=", "b")]`, facet.groupId);

    expect(JSON.stringify(model.domain)).toInclude("b");
    expect(model.groupBy).toEqual(["properties.p1"]);
});

test("a favorite group-by on a deleted property drops the group-by, not the search", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <field name="properties"/>
            </search>
        `,
        irFilters: [
            {
                context: "{'group_by': ['properties.gone']}",
                domain: "[('foo', '=', 'a')]",
                id: 1,
                is_default: true,
                name: "Fav",
                sort: "[]",
                user_ids: [2],
            },
        ],
    });
    model._fetchPropertiesDefinition = async () => [
        { definitionRecordId: 1, definitionRecordName: "Parent", definitions: [] },
    ];
    const facet = model.facets.find((/** @type {any} */ f) => f.type === "favorite");

    await model.splitAndAddDomain(`[("foo", "=", "b")]`, facet.groupId);

    expect(JSON.stringify(model.domain)).toInclude("b");
    expect(model.groupBy).toEqual([]);
});

test("search() invalidates the memos consumers detect changes by", async () => {
    const model = await createSearchModel({
        searchViewArch: `<search><filter name="filt" string="Filt" domain="[('foo','=','a')]"/></search>`,
        groupBy: ["foo"],
    });
    const before = {
        context: model.context,
        domain: model.domain,
        orderBy: model.orderBy,
    };

    model.search();

    // WithSearch passes these down as slot props and Owl skips a child whose
    // props are all strictly identical, so re-running the search has to hand
    // out new references or it never reaches the view.
    expect(model.context === before.context).toBe(false);
    expect(model.domain === before.domain).toBe(false);
    expect(model.orderBy === before.orderBy).toBe(false);
    expect(model.domain).toEqual(before.domain);
});

describe("invisible search items", () => {
    test("an item whose invisible condition holds is left out", async () => {
        const model = await createSearchModel({
            searchViewArch: `
                <search>
                    <filter name="shown" string="Shown" domain="[]"/>
                    <filter name="hidden" string="Hidden" domain="[]" invisible="context.get('hide')"/>
                </search>`,
            context: { hide: true },
        });
        expect(
            model
                .getSearchItems((/** @type {any} */ i) => i.type === "filter")
                .map((/** @type {any} */ i) => i.description),
        ).toEqual(["Shown"]);
    });

    test("an empty list reads as visible, like every other view modifier", async () => {
        const model = await createSearchModel({
            searchViewArch: `
                <search>
                    <filter name="a" string="A" domain="[]" invisible="context.get('ids')"/>
                </search>`,
            context: { ids: [] },
        });
        expect(
            model
                .getSearchItems((/** @type {any} */ i) => i.type === "filter")
                .map((/** @type {any} */ i) => i.description),
        ).toEqual(["A"]);
    });

    test("an unevaluatable condition warns and hides nothing", async () => {
        patchWithCleanup(console, { warn: () => expect.step("warn") });
        const model = await createSearchModel({
            searchViewArch: `
                <search>
                    <filter name="a" string="A" domain="[]" invisible="no_such_name"/>
                    <filter name="b" string="B" domain="[]"/>
                </search>`,
        });

        // The control panel reads every menu through getSearchItems; one bad
        // arch expression must not take all of them down.
        expect(
            model
                .getSearchItems((/** @type {any} */ i) => i.type === "filter")
                .map((/** @type {any} */ i) => i.description),
        ).toEqual(["A", "B"]);
        expect.verifySteps(["warn"]);
    });
});

test("getSearchItems is ordered whether or not a favorite is in scope", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <field name="foo"/>
                <filter name="a" string="A" domain="[]"/>
                <separator/>
                <filter name="b" string="B" domain="[]"/>
            </search>`,
        irFilters: [
            {
                context: "{}",
                domain: "[]",
                id: 1,
                is_default: false,
                name: "Fav",
                sort: "[]",
                user_ids: [2],
            },
        ],
    });

    const withoutFavorite = model
        .getSearchItems((/** @type {any} */ i) => i.type === "filter")
        .map((/** @type {any} */ i) => i.description);
    const withFavorite = model
        .getSearchItems((/** @type {any} */ i) =>
            ["filter", "favorite"].includes(i.type),
        )
        .map((/** @type {any} */ i) => i.description);

    expect(withoutFavorite).toEqual(["A", "B"]);
    expect(withFavorite.filter((/** @type {any} */ d) => d !== "Fav")).toEqual(
        withoutFavorite,
    );
});

test("the Activities block ANDs across its invisible separator", async () => {
    // Verbatim in shape from account/views/account_move_views.xml, repeated in
    // 44 shipped search views. The activity systray combines
    // search_default_filter_activities_my with one of the date filters; they sit
    // on either side of `<separator invisible="1"/>`, so they must AND. The
    // three date filters share a group and must OR. Honouring `invisible` on the
    // separator turns the first pair into an OR.
    const arch = `
        <search>
            <filter string="Archived" name="inactive" domain="[('bar', '=', False)]"/>
            <separator/>
            <filter name="filter_activities_my" string="My Activities" invisible="1"
                    domain="[('foo', '=', 'mine')]"/>
            <separator invisible="1"/>
            <filter name="activities_overdue" invisible="1" string="Late"
                    domain="[('foo', '=', 'late')]"/>
            <filter name="activities_today" invisible="1" string="Today"
                    domain="[('foo', '=', 'today')]"/>
        </search>`;

    const acrossSeparator = await createSearchModel({
        searchViewArch: arch,
        context: {
            search_default_filter_activities_my: 1,
            search_default_activities_overdue: 1,
        },
    });
    expect(acrossSeparator.domain).toEqual([
        "&",
        ["foo", "=", "mine"],
        ["foo", "=", "late"],
    ]);

    const withinGroup = await createSearchModel({
        searchViewArch: arch,
        context: {
            search_default_activities_overdue: 1,
            search_default_activities_today: 1,
        },
    });
    expect(withinGroup.domain).toEqual([
        "|",
        ["foo", "=", "late"],
        ["foo", "=", "today"],
    ]);
});

test("property group-bys join the group-by group instead of one group each", async () => {
    // Group-bys form a SINGLE query group, so activating several of them yields
    // one ">"-separated facet the user can drop in one click. Property
    // group-bys used to get a group of their own, so N of them produced N
    // chips, each needing its own click to remove.
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <field name="properties"/>
                <filter string="Foo" name="group_by_foo" context="{'group_by': 'foo'}"/>
            </search>
        `,
    });
    model._fetchPropertiesDefinition = async () => [
        {
            definitionRecordId: 1,
            definitionRecordName: "Parent",
            definitions: [
                { name: "p1", string: "P1", type: "char" },
                { name: "p2", string: "P2", type: "char" },
            ],
        },
    ];
    await model.fillSearchViewItemsProperty();

    const archGroupBy = Object.values(model.searchItems).find(
        (item) => item.name === "group_by_foo",
    );
    const propertyGroupBys = Object.values(model.searchItems).filter(
        (item) => item.isProperty,
    );
    expect(propertyGroupBys).toHaveLength(2);
    expect(propertyGroupBys.map((item) => item.groupId)).toEqual([
        archGroupBy.groupId,
        archGroupBy.groupId,
    ]);

    model.toggleSearchItem(propertyGroupBys[0].id);
    model.toggleSearchItem(propertyGroupBys[1].id);
    expect(model.facets).toHaveLength(1);
    expect(model.facets[0].values).toEqual(["P1", "P2"]);

    model.deactivateGroup(model.facets[0].groupId);
    expect(model.facets).toHaveLength(0);
});

test("property group-bys form their own group when the view has none", async () => {
    const model = await createSearchModel({
        searchViewArch: `
            <search>
                <field name="properties"/>
            </search>
        `,
    });
    model._fetchPropertiesDefinition = async () => [
        {
            definitionRecordId: 1,
            definitionRecordName: "Parent",
            definitions: [
                { name: "p1", string: "P1", type: "char" },
                { name: "p2", string: "P2", type: "char" },
            ],
        },
    ];
    await model.fillSearchViewItemsProperty();

    const groupIds = new Set(
        Object.values(model.searchItems)
            .filter((item) => item.isProperty)
            .map((item) => item.groupId),
    );
    expect(groupIds.size).toBe(1);
});
