import {describe, expect, test} from "@odoo/hoot";
import {mockTimeZone} from "@odoo/hoot-mock";
import {makeMockEnv} from "@web/../tests/web_test_helpers";
import {condition, connector} from "@web/core/tree";
import {virtualOperatorFunctions} from "@web/core/tree";
import {TreeEditor} from "@web/components/tree_editor";

import "@date_range/js/date_range_tree_processor";
import "@date_range/js/tree_editor.esm";

describe.current.tags("headless");

const RANGES = [
    {
        id: 7,
        name: "Q1 2030",
        date_start: "2030-01-01",
        date_end: "2030-03-31",
        type_id: [3, "Quarter"],
    },
    {
        id: 8,
        name: "H1 2030",
        date_start: "2030-01-01",
        date_end: "2030-06-30",
        type_id: [4, "Half"],
    },
];

const dateOptions = {getFieldDef: () => ({type: "date"})};
const datetimeOptions = {getFieldDef: () => ({type: "datetime"})};

/** Shorthand description of a tree, for readable assertions. */
function shape(tree) {
    if (tree.type === "condition") {
        return `${tree.operator}(${JSON.stringify(tree.value)})`;
    }
    return `${tree.value}[${tree.children.map(shape).join(", ")}]`;
}

/** A stand-in for a mounted TreeEditor: only what updateNode() touches. */
function makeEditor(fieldType) {
    const editor = Object.create(TreeEditor.prototype);
    editor.env = {domain: {dateRanges: RANGES}};
    editor.getFieldDef = () => ({type: fieldType});
    editor.prepareInfo = async () => {};
    editor.render = () => {};
    editor.notifyChanges = () => {};
    editor.props = {update: () => {}};
    return editor;
}

test("a period is recognised from the <= .. >= pair, not the mirrored one", async () => {
    await makeMockEnv();
    const pair = (op1, value1, op2, value2) =>
        connector("&", [condition("d", op1, value1), condition("d", op2, value2)]);

    // The web client's own "in range" operator claims the natural order first,
    // so a period has to be spelled the other way round or the two would fight
    // over the same pair. date.range.get_domain() emits this order to match.
    expect(
        shape(
            virtualOperatorFunctions.introduceVirtualOperators(
                pair("<=", "2030-12-31", ">=", "2030-01-01"),
                dateOptions
            )
        )
    ).toBe('daterange(["2030-12-31","2030-01-01"])');

    expect(
        virtualOperatorFunctions.introduceVirtualOperators(
            pair(">=", "2030-01-01", "<=", "2030-12-31"),
            dateOptions
        ).operator
    ).toBe("in range");
});

test("a period survives the trip to a domain and back", async () => {
    await makeMockEnv();
    const period = condition("d", "daterange", ["2030-12-31", "2030-01-01"]);
    const eliminated = virtualOperatorFunctions.eliminateVirtualOperators(
        period,
        dateOptions
    );
    expect(shape(eliminated)).toBe('&[<=("2030-12-31"), >=("2030-01-01")]');
    expect(
        shape(
            virtualOperatorFunctions.introduceVirtualOperators(eliminated, dateOptions)
        )
    ).toBe('daterange(["2030-12-31","2030-01-01"])');
});

test("an unrelated <select> on the page cannot change the operator", async () => {
    await makeMockEnv();
    // The operator used to be read out of document.getElementsByTagName("select")[0],
    // so any unrelated dropdown that happened to be mounted decided which
    // date range type a condition belonged to.
    const select = document.createElement("select");
    const option = document.createElement("option");
    option.value = '"daterange_42"';
    option.selected = true;
    select.appendChild(option);
    document.body.appendChild(select);
    try {
        const tree = connector("&", [
            condition("d", "<=", "2030-12-31"),
            condition("d", ">=", "2030-01-01"),
        ]);
        expect(
            virtualOperatorFunctions.introduceVirtualOperators(tree, dateOptions)
                .operator
        ).toBe("daterange");
    } finally {
        select.remove();
    }
});

test("a non-string operator does not crash the elimination pass", async () => {
    await makeMockEnv();
    expect(() =>
        virtualOperatorFunctions.eliminateVirtualOperators(
            condition("d", 7, 1),
            dateOptions
        )
    ).not.toThrow();
});

test("picking a period covers both of its end days on a datetime field", async () => {
    await makeMockEnv();
    mockTimeZone(-6); // America/Mexico_City, where this fork is deployed
    const node = {
        type: "condition",
        path: "d",
        operator: "=",
        value: false,
        negate: false,
    };
    await makeEditor("datetime").updateLeafOperator(node, "daterange", false);

    // value[0] feeds `<=` and value[1] feeds `>=`, so the end date has to be the
    // last instant of its day and the start the first instant of its. Reversing
    // them drops the whole first and last day of every period.
    expect(node.value).toEqual(["2030-04-01 05:59:59", "2030-01-01 06:00:00"]);

    const domain = virtualOperatorFunctions.eliminateVirtualOperators(
        condition("d", node.operator, node.value),
        datetimeOptions
    );
    expect(shape(domain)).toBe(
        '&[<=("2030-04-01 05:59:59"), >=("2030-01-01 06:00:00")]'
    );
});

test("the period's end days follow the user's timezone", async () => {
    await makeMockEnv();
    // Deliberately not the host's offset: the bounds are computed in the user's
    // timezone and serialised to UTC, and a test pinned to the machine's own
    // zone would pass on arithmetic that never converts.
    mockTimeZone(+5.5);
    const node = {
        type: "condition",
        path: "d",
        operator: "=",
        value: false,
        negate: false,
    };
    await makeEditor("datetime").updateLeafOperator(node, "daterange", false);
    expect(node.value).toEqual(["2030-03-31 18:29:59", "2029-12-31 18:30:00"]);
});

test("a date field keeps plain dates", async () => {
    await makeMockEnv();
    mockTimeZone(-6);
    const node = {
        type: "condition",
        path: "d",
        operator: "=",
        value: false,
        negate: false,
    };
    await makeEditor("date").updateLeafOperator(node, "daterange", false);
    expect(node.value).toEqual(["2030-03-31", "2030-01-01"]);
});

test("negation given to updateLeafOperator reaches the node", async () => {
    await makeMockEnv();
    const node = {
        type: "condition",
        path: "d",
        operator: "=",
        value: false,
        negate: false,
    };
    await makeEditor("date").updateLeafOperator(node, "daterange", true);
    expect(node.negate).toBe(true);
});

test("each condition offers the periods of its own type", async () => {
    await makeMockEnv();
    const editor = makeEditor("date");
    // Touch the other typed condition first: the choice used to be remembered
    // on the component, so every row showed the last-edited row's type.
    editor.getValueEditorInfo({
        type: "condition",
        path: "d",
        operator: "daterange_4",
        value: ["2030-06-30", "2030-01-01"],
    });
    const info = editor.getValueEditorInfo({
        type: "condition",
        path: "d",
        operator: "daterange_3",
        value: ["2030-03-31", "2030-01-01"],
    });
    const props = info.extractProps({
        value: ["2030-03-31", "2030-01-01"],
        update: () => {},
    });
    expect(props.options).toEqual([[7, "Q1 2030"]]);
    expect(props.value).toBe(7);
});

test("reading the value editor does not rewrite the condition", async () => {
    await makeMockEnv();
    const editor = makeEditor("date");
    const info = editor.getValueEditorInfo({
        type: "condition",
        path: "d",
        operator: "daterange",
        value: ["1999-01-01", "1999-01-01"],
    });
    let updated = false;
    info.extractProps({
        value: ["1999-01-01", "1999-01-01"],
        update: () => {
            updated = true;
        },
    });
    // A value that matches no known period leaves the condition alone; it used
    // to be silently overwritten with the first period in the list, during
    // rendering.
    expect(updated).toBe(false);
});
