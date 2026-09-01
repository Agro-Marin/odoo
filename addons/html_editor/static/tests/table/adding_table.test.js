import { findInSelection } from "@html_editor/utils/selection";
import { expect, test } from "@odoo/hoot";
import { click, edit, press, queryOne, waitFor } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";

import { setupEditor } from "../_helpers/editor.js";
import { unformat } from "../_helpers/format.js";
import { getContent } from "../_helpers/selection.js";
import { expectElementCount } from "../_helpers/ui_expectations.js";
import { insertText } from "../_helpers/user_actions.js";

function expectContentToBe(el, html) {
    expect(getContent(el)).toBe(unformat(html));
}

test.tags("desktop");
test("can add a table using the powerbox and keyboard", async () => {
    const { el, editor } = await setupEditor("<p>a[]</p>");
    await expectElementCount(".o-we-powerbox", 0);
    expectContentToBe(el, `<p>a[]</p>`);

    await insertText(editor, "/");
    await waitFor(".o-we-powerbox");
    await expectElementCount(".o-we-tablepicker", 0);

    await insertText(editor, "table");
    await animationFrame();

    await press("Enter");
    await waitFor(".o-we-tablepicker");
    await expectElementCount(".o-we-powerbox", 0);

    await press("Enter");
    await animationFrame();
    await expectElementCount(".o-we-powerbox", 0);
    await expectElementCount(".o-we-tablepicker", 0);
    expectContentToBe(
        el,
        `<p>a</p>
        <table class="table table-bordered o_table">
            <tbody>
                <tr>
                    <td><p o-we-hint-text='Type "/" for commands' class="o-we-hint">[]<br></p></td>
                    <td><p><br></p></td>
                    <td><p><br></p></td>
                </tr>
                <tr>
                    <td><p><br></p></td>
                    <td><p><br></p></td>
                    <td><p><br></p></td>
                </tr>
                <tr>
                    <td><p><br></p></td>
                    <td><p><br></p></td>
                    <td><p><br></p></td>
                </tr>
            </tbody>
        </table>
        <p data-selection-placeholder="" style="margin: -9px 0px 8px;"><br></p>`,
    );
});

test.tags("mobile");
test("on mobile, the table command asks for a size instead of inserting 3x3", async () => {
    const { el, editor } = await setupEditor("<p>a[]</p>");
    await insertText(editor, "/");
    await waitFor(".o-we-powerbox");
    await expectElementCount(".o-we-mobile-tablepicker", 0);

    await insertText(editor, "table");
    await animationFrame();

    await press("Enter");
    await waitFor(".o-we-mobile-tablepicker");
    await expectElementCount(".o-we-powerbox", 0);
    // Nothing is inserted until the size is confirmed. The caret marker is
    // gone from the editable because the picker focuses its first input.
    expectContentToBe(el, "<p>a</p>");
    expect(el.querySelector("table")).toBe(null);

    await press("Enter");
    await animationFrame();
    await expectElementCount(".o-we-mobile-tablepicker", 0);
    expectContentToBe(
        el,
        `<p>a</p>
        <table class="table table-bordered o_table">
            <tbody>
                <tr>
                    <td><p o-we-hint-text='Type "/" for commands' class="o-we-hint">[]<br></p></td>
                    <td><p><br></p></td>
                    <td><p><br></p></td>
                </tr>
                <tr>
                    <td><p><br></p></td>
                    <td><p><br></p></td>
                    <td><p><br></p></td>
                </tr>
                <tr>
                    <td><p><br></p></td>
                    <td><p><br></p></td>
                    <td><p><br></p></td>
                </tr>
            </tbody>
        </table>
        <p data-selection-placeholder="" style="margin: -9px 0px 8px;"><br></p>`,
    );
});

test.tags("mobile");
test("on mobile, Apply inserts the table at the size that was typed", async () => {
    const { el, editor } = await setupEditor("<p>a[]</p>");
    await insertText(editor, "/");
    await waitFor(".o-we-powerbox");
    await insertText(editor, "table");
    await animationFrame();
    await press("Enter");
    await waitFor(".o-we-mobile-tablepicker");

    await click("#o_we_table_rows");
    await edit("1");
    await click("#o_we_table_cols");
    await edit("2");
    await click(".o-we-mobile-tablepicker-apply");
    await animationFrame();

    await expectElementCount(".o-we-mobile-tablepicker", 0);
    expectContentToBe(
        el,
        `<p>a</p>
        <table class="table table-bordered o_table">
            <tbody>
                <tr>
                    <td><p o-we-hint-text='Type "/" for commands' class="o-we-hint">[]<br></p></td>
                    <td><p><br></p></td>
                </tr>
            </tbody>
        </table>
        <p data-selection-placeholder="" style="margin: -9px 0px 8px;"><br></p>`,
    );
});

test.tags("mobile");
test("on mobile, Discard closes the picker without inserting a table", async () => {
    const { el, editor } = await setupEditor("<p>a[]</p>");
    await insertText(editor, "/");
    await waitFor(".o-we-powerbox");
    await insertText(editor, "table");
    await animationFrame();
    await press("Enter");
    await waitFor(".o-we-mobile-tablepicker");

    await click(".o-we-mobile-tablepicker-discard");
    await animationFrame();
    await expectElementCount(".o-we-mobile-tablepicker", 0);
    expectContentToBe(el, "<p>a[]</p>");
});

test.tags("desktop");
test("can close table picker with escape", async () => {
    const { el, editor } = await setupEditor("<p>a[]</p>");
    await insertText(editor, "/");
    await waitFor(".o-we-powerbox");
    await insertText(editor, "table");
    expectContentToBe(el, "<p>a/table[]</p>");
    await animationFrame();
    await press("Enter");
    await expectElementCount(".o-we-tablepicker", 1);
    expectContentToBe(el, "<p>a[]</p>");
    await press("escape");
    await animationFrame();
    await expectElementCount(".o-we-tablepicker", 0);
});

test.tags("iframe", "desktop");
test("in iframe, can add a table using the powerbox and keyboard", async () => {
    const { el, editor } = await setupEditor("<p>a[]</p>", {
        props: { iframe: true },
    });
    await expectElementCount(".o-we-powerbox", 0);
    expect(getContent(el)).toBe(`<p>a[]</p>`);
    expect(":iframe .o_table").toHaveCount(0);

    await insertText(editor, "/");
    await waitFor(".o-we-powerbox");
    await expectElementCount(".o-we-tablepicker", 0);

    await insertText(editor, "table");
    await animationFrame();

    await press("Enter");
    await waitFor(".o-we-tablepicker");
    await expectElementCount(".o-we-powerbox", 0);

    await press("Enter");
    await animationFrame();
    await expectElementCount(".o-we-powerbox", 0);
    await expectElementCount(".o-we-tablepicker", 0);
    expect(":iframe .o_table").toHaveCount(1);
});

test.tags("desktop");
test("Expand columns in the correct direction in 'rtl'", async () => {
    const { editor } = await setupEditor("<p>a[]</p>", {
        config: {
            direction: "rtl",
        },
    });
    await insertText(editor, "/table");
    await press("Enter");
    await waitFor(".o-we-tablepicker");

    const tablePickerOverlay = queryOne(".overlay");
    expect(tablePickerOverlay).toHaveStyle({ right: /px$/ });
    const right = tablePickerOverlay.style.right;
    const width3Columns = tablePickerOverlay.getBoundingClientRect().width;
    expect(".o-we-cell.active").toHaveCount(9);

    await press("ArrowLeft");
    await animationFrame();
    expect(tablePickerOverlay.getBoundingClientRect().width).toBeGreaterThan(
        width3Columns,
    );
    expect(tablePickerOverlay).toHaveStyle({ right });
    expect(".o-we-cell.active").toHaveCount(12);

    await press("ArrowRight");
    await animationFrame();
    expect(".o-we-cell.active").toHaveCount(9);
    expect(tablePickerOverlay).toHaveStyle({ right });

    await press("ArrowRight");
    await animationFrame();
    expect(tablePickerOverlay.getBoundingClientRect().width).toBeLessThan(
        width3Columns,
    );
    expect(tablePickerOverlay).toHaveStyle({ right });
    expect(".o-we-cell.active").toHaveCount(6);
});

test.tags("desktop");
test("add table inside empty list", async () => {
    const { el, editor } = await setupEditor("<ul><li>[]<br></li></ul>");

    await insertText(editor, "/");
    await waitFor(".o-we-powerbox");
    await expectElementCount(".o-we-tablepicker", 0);

    await insertText(editor, "table");
    await animationFrame();

    await press("Enter");
    await waitFor(".o-we-tablepicker");
    await expectElementCount(".o-we-powerbox", 0);

    await press("Enter");
    await animationFrame();
    await expectElementCount(".o-we-powerbox", 0);
    await expectElementCount(".o-we-tablepicker", 0);
    expectContentToBe(
        el,
        `<ul>
            <li>
                <br>
                <table class="table table-bordered o_table">
                    <tbody>
                        <tr>
                            <td><p o-we-hint-text='Type "/" for commands' class="o-we-hint">[]<br></p></td>
                            <td><p><br></p></td>
                            <td><p><br></p></td>
                        </tr>
                        <tr>
                            <td><p><br></p></td>
                            <td><p><br></p></td>
                            <td><p><br></p></td>
                        </tr>
                        <tr>
                            <td><p><br></p></td>
                            <td><p><br></p></td>
                            <td><p><br></p></td>
                        </tr>
                    </tbody>
                </table>
            </li>
        </ul>`,
    );
});

test.tags("desktop");
test("add table inside non-empty list", async () => {
    const { el, editor } = await setupEditor("<ul><li>abc[]</li></ul>");

    await insertText(editor, "/");
    await waitFor(".o-we-powerbox");
    await expectElementCount(".o-we-tablepicker", 0);

    await insertText(editor, "table");
    await animationFrame();

    await press("Enter");
    await waitFor(".o-we-tablepicker");
    await expectElementCount(".o-we-powerbox", 0);

    await press("Enter");
    await animationFrame();
    await expectElementCount(".o-we-powerbox", 0);
    await expectElementCount(".o-we-tablepicker", 0);
    expectContentToBe(
        el,
        `<ul>
            <li>
                abc
                <table class="table table-bordered o_table">
                    <tbody>
                        <tr>
                            <td><p o-we-hint-text='Type "/" for commands' class="o-we-hint">[]<br></p></td>
                            <td><p><br></p></td>
                            <td><p><br></p></td>
                        </tr>
                        <tr>
                            <td><p><br></p></td>
                            <td><p><br></p></td>
                            <td><p><br></p></td>
                        </tr>
                        <tr>
                            <td><p><br></p></td>
                            <td><p><br></p></td>
                            <td><p><br></p></td>
                        </tr>
                    </tbody>
                </table>
            </li>
        </ul>`,
    );
});

test.tags("desktop");
test("should close the table picker when any key except arrow keys pressed", async () => {
    const { el, editor } = await setupEditor("<p>a[]</p>");
    await insertText(editor, "/");
    await waitFor(".o-we-powerbox");
    await insertText(editor, "table");
    expectContentToBe(el, "<p>a/table[]</p>");
    await animationFrame();
    await press("Enter");
    await expectElementCount(".o-we-tablepicker", 1);
    expectContentToBe(el, "<p>a[]</p>");
    await insertText(editor, "b");
    await animationFrame();
    await expectElementCount(".o-we-tablepicker", 0);
    expectContentToBe(el, "<p>ab[]</p>");
    await insertText(editor, "/");
    await waitFor(".o-we-powerbox");
    await insertText(editor, "table");
    expectContentToBe(el, "<p>ab/table[]</p>");
    await animationFrame();
    await press("Enter");
    await expectElementCount(".o-we-tablepicker", 1);
    expectContentToBe(el, "<p>ab[]</p>");
    await insertText(editor, "/");
    await animationFrame();
    await expectElementCount(".o-we-tablepicker", 0);
});

test.tags("desktop");
test("should not navigate table cells when table picker is open", async () => {
    const { el, editor } = await setupEditor(
        unformat(`
            <table class="table table-bordered o_table">
                <tbody>
                    <tr>
                        <td><p><br></p></td>
                    </tr>
                    <tr>
                        <td><p><br></p></td>
                    </tr>
                    <tr>
                        <td><p>[]<br></p></td>
                    </tr>
                </tbody>
            </table>
        `),
    );
    await insertText(editor, "/");
    await waitFor(".o-we-powerbox");

    await insertText(editor, "table");
    await animationFrame();

    await press("Enter");
    await waitFor(".o-we-tablepicker");

    press("ArrowUp");
    await animationFrame();
    press("ArrowUp");
    await animationFrame();
    press("Enter");
    await animationFrame();
    expectContentToBe(
        el,
        `
            <p data-selection-placeholder=""><br></p>
            <table class="table table-bordered o_table">
                <tbody>
                    <tr>
                        <td><p><br></p></td>
                    </tr>
                    <tr>
                        <td><p><br></p></td>
                    </tr>
                    <tr>
                        <td>
                            <p data-selection-placeholder=""><br></p>
                            <table class="table table-bordered o_table">
                                <tbody>
                                    <tr>
                                        <td><p o-we-hint-text='Type "/" for commands' class="o-we-hint">[]<br></p></td>
                                        <td><p><br></p></td>
                                        <td><p><br></p></td>
                                    </tr>
                                </tbody>
                            </table>
                            <p data-selection-placeholder="" style="margin: -9px 0px 8px;"><br></p>
                        </td>
                    </tr>
                </tbody>
            </table>
            <p data-selection-placeholder="" style="margin: -9px 0px 8px;"><br></p>
        `,
    );
});

test.tags("desktop");
test("should not navigate table cells when powerbox is open", async () => {
    const { el, editor } = await setupEditor(
        unformat(`
            <table class="table table-bordered o_table">
                <tbody>
                    <tr>
                        <td><p><br></p></td>
                    </tr>
                    <tr>
                        <td><p>test[]</p></td>
                    </tr>
                    <tr>
                        <td><p><br></p></td>
                    </tr>
                </tbody>
            </table>
        `),
    );

    await insertText(editor, "/");
    await waitFor(".o-we-powerbox");

    const secondTd = el.querySelectorAll("td")[1];

    let selectedTd = findInSelection(
        editor.shared.selection.getEditableSelection(),
        "td",
    );
    expect(selectedTd).toBe(secondTd);

    press("ArrowUp");
    await animationFrame();

    selectedTd = findInSelection(editor.shared.selection.getEditableSelection(), "td");
    expect(selectedTd).toBe(secondTd);

    press("ArrowDown");
    await animationFrame();

    selectedTd = findInSelection(editor.shared.selection.getEditableSelection(), "td");
    expect(selectedTd).toBe(secondTd);

    press("Enter");
    await animationFrame();

    expectContentToBe(
        el,
        `
            <p data-selection-placeholder=""><br></p>
            <table class="table table-bordered o_table">
                <tbody>
                    <tr>
                        <td><p><br></p></td>
                        </tr>
                    <tr>
                        <td><h1>test[]</h1></td>
                    </tr>
                    <tr>
                        <td><p><br></p></td>
                    </tr>
                </tbody>
            </table>
            <p data-selection-placeholder="" style="margin: -9px 0px 8px;"><br></p>
        `,
    );
});
