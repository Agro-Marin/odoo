// @ts-check
import { describe, expect, test } from "@odoo/hoot";
import { listStylingMixin } from "@web/views/list/list_styling";

describe.current.tags("headless");

/** @param {Record<string, any>} [overrides] */
function makeRenderer(overrides = {}) {
    return {
        ...listStylingMixin,
        fields: { foo: { type: "char" }, qty: { type: "integer" } },
        cellClassByColumn: {},
        _readonlyCache: null,
        editedRecord: null,
        canResequenceRows: false,
        props: {
            list: { orderBy: [], evalContext: {} },
            archInfo: { decorations: [] },
            activeActions: { edit: true },
        },
        isSortable: () => true,
        isNumericColumn: (column) => column.name === "qty",
        isInlineEditable: () => true,
        ...overrides,
    };
}

/** @param {Record<string, any>} [overrides] */
function makeRecord(overrides = {}) {
    return /** @type {any} */ ({
        id: "r1",
        data: { foo: "a", qty: 0 },
        evalContextWithVirtualIds: { foo: "a", qty: 0 },
        selected: false,
        isInEdition: false,
        isNew: false,
        model: { multiEdit: false },
        isFieldInvalid: () => false,
        ...overrides,
    });
}

const fooColumn = {
    id: "c1",
    name: "foo",
    type: "field",
    readonly: "False",
    required: "False",
    decorations: {},
};

test("getColumnClass marks the sorted column only when it has a label", () => {
    const r = makeRenderer();
    r.props.list.orderBy = [{ name: "foo", asc: true }];
    expect(r.getColumnClass({ name: "foo", hasLabel: true })).toMatch(/table-active/);
    expect(r.getColumnClass({ name: "foo", hasLabel: false })).not.toMatch(
        /table-active/,
    );
    expect(
        r.getColumnClass({ name: "foo", widget: "handle", hasLabel: true }),
    ).not.toMatch(/table-active/);
    expect(r.getColumnClass({ name: "qty", widget: "float_time" })).toBe(
        "align-middle o_column_sortable position-relative cursor-pointer o_list_number_th o_float_time_cell",
    );
});

test("getRowClass composes decorations, selection, edition and drag", () => {
    const r = makeRenderer({ canResequenceRows: true });
    r.props.archInfo.decorations = [
        { condition: "qty == 0", class: "text-danger" },
        { condition: "qty > 0", class: "text-success" },
    ];
    expect(r.getRowClass(makeRecord({ selected: true, isInEdition: true }))).toBe(
        "text-danger table-info o_data_row_selected o_selected_row o_row_draggable",
    );
});

test("getCellClass memoizes the static part per column and evaluates the rest per record", () => {
    const r = makeRenderer();
    const first = r.getCellClass(fooColumn, makeRecord());
    expect(first).toBe("o_data_cell o_field_cell o_list_char cursor-pointer");
    expect(r.cellClassByColumn.c1).toBe("o_data_cell o_field_cell o_list_char");
    const required = { ...fooColumn, required: "qty == 0" };
    expect(r.getCellClass(required, makeRecord({ isFieldInvalid: () => true }))).toBe(
        "o_data_cell o_field_cell o_list_char o_required_modifier o_invalid_cell cursor-pointer",
    );
});

test("getCellClass applies decorations only while the formatter is in use", () => {
    const r = makeRenderer();
    const column = { ...fooColumn, decorations: { danger: "qty == 0" } };
    expect(r.getCellClass(column, makeRecord())).toMatch(/text-danger/);
    expect(r.getCellClass(column, makeRecord({ isInEdition: true }))).not.toMatch(
        /text-danger/,
    );
    expect(r.getCellClass({ ...column, widget: "char" }, makeRecord())).not.toMatch(
        /text-danger/,
    );
});

test("a readonly cell on the edited row is muted, elsewhere it is clickable", () => {
    const edited = makeRecord({ isInEdition: true });
    const r = makeRenderer({ editedRecord: edited });
    const column = { ...fooColumn, readonly: "True" };
    expect(r.getCellClass(column, edited)).toMatch(/o_readonly_modifier text-muted$/);
    expect(r.getCellClass(column, makeRecord({ id: "r2" }))).toMatch(
        /o_readonly_modifier cursor-pointer$/,
    );
});

test("the readonly cache answers the second read without re-evaluating", () => {
    const r = makeRenderer({ _readonlyCache: new Map() });
    let evaluations = 0;
    const record = makeRecord({
        get evalContextWithVirtualIds() {
            evaluations++;
            return { qty: 0 };
        },
    });
    expect(r.isCellReadonly({ ...fooColumn, readonly: "qty == 0" }, record)).toBe(true);
    expect(r.isCellReadonly({ ...fooColumn, readonly: "qty == 0" }, record)).toBe(true);
    expect(evaluations).toBe(1);
});

test("isRecordReadonly: new records are editable, edit=False and non-inline edition are not", () => {
    const r = makeRenderer();
    expect(r.isRecordReadonly(makeRecord({ isNew: true }))).toBe(false);
    expect(r.isRecordReadonly(makeRecord())).toBe(false);
    r.props.activeActions.edit = false;
    expect(r.isRecordReadonly(makeRecord())).toBe(true);
    const notInline = makeRenderer({ isInlineEditable: () => false });
    expect(notInline.isRecordReadonly(makeRecord({ isInEdition: true }))).toBe(true);
    expect(
        notInline.isRecordReadonly(
            makeRecord({ isInEdition: true, model: { multiEdit: true } }),
        ),
    ).toBe(false);
});

test("a property column whose value the record lacks gets no cell class", () => {
    const r = makeRenderer();
    expect(
        r.getCellClass(
            { ...fooColumn, name: "missing", relatedPropertyField: {} },
            makeRecord(),
        ),
    ).toBe("");
});

test("getCellTitle only titles the text-like types", () => {
    const r = makeRenderer();
    expect(r.getCellTitle({ name: "foo" }, makeRecord(), "shown")).toBe("shown");
    expect(r.getCellTitle({ name: "qty" }, makeRecord(), "3")).toBe(undefined);
});
