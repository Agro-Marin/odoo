import {
    addTables,
    bootstrapToTable,
    cardToTable,
    classToStyle,
    createMso,
    formatTables,
    getCSSRules,
    listGroupToTable,
    normalizeColors,
    normalizeRem,
    toInline,
} from "@mail/views/web/fields/html_mail_field/convert_inline";
import { beforeEach, describe, expect, getFixture, test } from "@odoo/hoot";
import { enableTransitions } from "@odoo/hoot-mock";

import {
    getGridHtml,
    getRegularGridHtml,
    getRegularTableHtml,
    getTableHtml,
    getTdHtml,
} from "./utils.js";

const TEST_WIDTH = 800;
const TEST_HEIGHT = 600;

let editable;
// Remove the marker set on generated elements for the benefit of re-runs of
// `toInline` on its own output: it is not part of the tested behaviors.
function removeGeneratedMarkers(element) {
    element.querySelectorAll("[data-o-mail-generated]").forEach((node) => {
        node.removeAttribute("data-o-mail-generated");
    });
}
function testConvertGrid({ before, after, title, stepFunction }) {
    editable.innerHTML = before;
    (stepFunction || bootstrapToTable)(editable);
    // Remove class that is added by `bootstrapToTable` for use in
    // further methods of `toInline`, and removed at the end of it.
    editable.querySelectorAll(".o_converted_col").forEach((node) => {
        node.classList.remove("o_converted_col");
        if (!node.classList.length) {
            node.removeAttribute("class");
        }
    });
    removeGeneratedMarkers(editable);
    expect(editable).toHaveInnerHTML(after, { message: title, type: "html" });
}

describe("Convert Bootstrap grids to tables", () => {
    // Test bootstrapToTable, cardToTable and listGroupToTable
    beforeEach(() => {
        editable = document.createElement("div");
        editable.style.setProperty("width", TEST_WIDTH + "px");
        editable.style.setProperty("height", TEST_HEIGHT + "px");
        getFixture().append(editable);
    });

    test("convert a single-row regular grid", async () => {
        // 1x1
        testConvertGrid({
            before: getRegularGridHtml(1, 1),
            after: getRegularTableHtml(1, 1, 12, 100, TEST_WIDTH),
            title: "should have converted a 1x1 grid to an equivalent table",
        });

        // 1x2
        testConvertGrid({
            before: getRegularGridHtml(1, 2),
            after: getRegularTableHtml(1, 2, 6, 50, TEST_WIDTH),
            title: "should have converted a 1x2 grid to an equivalent table",
        });

        // 1x3
        testConvertGrid({
            before: getRegularGridHtml(1, 3),
            after: getRegularTableHtml(1, 3, 4, 33.33, TEST_WIDTH),
            title: "should have converted a 1x3 grid to an equivalent table",
        });

        // 1x12
        testConvertGrid({
            before: getRegularGridHtml(1, 12),
            after: getRegularTableHtml(1, 12, 1, 8.33, TEST_WIDTH),
            title: "should have converted a 1x12 grid to an equivalent table",
        });
    });

    test("convert a single-row regular overflowing grid", async () => {
        // 1x13
        testConvertGrid({
            before: getRegularGridHtml(1, 13),
            after:
                getRegularTableHtml(1, 12, 1, 8.33, TEST_WIDTH).slice(0, -8) +
                `<tr>` +
                getTdHtml(1, "(0, 12)", TEST_WIDTH) +
                getTdHtml(11, "", TEST_WIDTH) +
                `</tr></table>`,
            title: "should have converted a 1x13 grid to an equivalent table (overflowing)",
        });

        // 1x14
        testConvertGrid({
            before: getRegularGridHtml(1, 14),
            after:
                getRegularTableHtml(1, 12, 1, 8.33, TEST_WIDTH).slice(0, -8) +
                `<tr>` +
                getTdHtml(1, "(0, 12)", TEST_WIDTH) +
                getTdHtml(1, "(0, 13)", TEST_WIDTH) +
                getTdHtml(10, "", TEST_WIDTH) +
                `</tr></table>`,
            title: "should have converted a 1x14 grid to an equivalent table (overflowing)",
        });

        // 1x25
        testConvertGrid({
            before: getRegularGridHtml(1, 25),
            after:
                getRegularTableHtml(1, 12, 1, 8.33, TEST_WIDTH).slice(0, -8) +
                getRegularTableHtml(1, 12, 1, 8.33, TEST_WIDTH)
                    .replace(/\(0, (\d+)\)/g, (s, c) => `(0, ${+c + 12})`)
                    .replace(/^<table[^<]*>/, "")
                    .slice(0, -8) +
                `<tr>` +
                getTdHtml(1, "(0, 24)", TEST_WIDTH) +
                getTdHtml(11, "", TEST_WIDTH) +
                `</tr></table>`,
            title: "should have converted a 1x25 grid to an equivalent table (overflowing)",
        });

        // 1x26
        testConvertGrid({
            before: getRegularGridHtml(1, 26),
            after:
                getRegularTableHtml(1, 12, 1, 8.33, TEST_WIDTH).slice(0, -8) +
                getRegularTableHtml(1, 12, 1, 8.33, TEST_WIDTH)
                    .replace(/\(0, (\d+)\)/g, (s, c) => `(0, ${+c + 12})`)
                    .replace(/^<table[^<]*>/, "")
                    .slice(0, -8) +
                `<tr>` +
                getTdHtml(1, "(0, 24)", TEST_WIDTH) +
                getTdHtml(1, "(0, 25)", TEST_WIDTH) +
                getTdHtml(10, "", TEST_WIDTH) +
                `</tr></table>`,
            title: "should have converted a 1x26 grid to an equivalent table (overflowing)",
        });
    });

    test("convert a multi-row regular grid", async () => {
        // 2x1
        testConvertGrid({
            before: getRegularGridHtml(2, 1),
            after: getRegularTableHtml(2, 1, 12, 100, TEST_WIDTH),
            title: "should have converted a 2x1 grid to an equivalent table",
        });

        // 2x[1,2]
        testConvertGrid({
            before: getRegularGridHtml(2, [1, 2]),
            after: getRegularTableHtml(2, [1, 2], [12, 6], [100, 50], TEST_WIDTH),
            title: "should have converted a 2x[1,2] grid to an equivalent table",
        });

        // 3x3
        testConvertGrid({
            before: getRegularGridHtml(3, 3),
            after: getRegularTableHtml(3, 3, 4, 33.33, TEST_WIDTH),
            title: "should have converted a 3x3 grid to an equivalent table",
        });

        // 3x[3,2,1]
        testConvertGrid({
            before: getRegularGridHtml(3, [3, 2, 1]),
            after: getRegularTableHtml(
                3,
                [3, 2, 1],
                [4, 6, 12],
                [33.33, 50, 100],
                TEST_WIDTH,
            ),
            title: "should have converted a 3x[3,2,1] grid to an equivalent table",
        });
    });

    test("convert a multi-row regular overflowing grid", async () => {
        // 2x[13,1]
        testConvertGrid({
            before: getRegularGridHtml(2, [13, 1]),
            after:
                getRegularTableHtml(1, 12, 1, 8.33, TEST_WIDTH).slice(0, -8) +
                `<tr>` +
                getTdHtml(1, "(0, 12)", TEST_WIDTH) +
                getTdHtml(11, "", TEST_WIDTH) + // 13 overflowed the row by 1 -> fill up
                `</tr>` +
                `<tr>${getTdHtml(12, "(1, 0)", TEST_WIDTH)}</tr></table>`, // 1 col with no size == col-12
            title: "should have converted a 2x[13,1] grid to an equivalent table (overflowing)",
        });

        // 2x[1,13]
        testConvertGrid({
            before: getRegularGridHtml(2, [1, 13]),
            after:
                getRegularTableHtml(2, [1, 12], [12, 1], [100, 8.33], TEST_WIDTH).slice(
                    0,
                    -8,
                ) +
                `<tr>` +
                getTdHtml(1, "(1, 12)", TEST_WIDTH) +
                getTdHtml(11, "", TEST_WIDTH) + // 13 overflowed the row by 1 -> fill up
                `</tr></table>`,
            title: "should have converted a 2x[1,13] grid to an equivalent table (overflowing)",
        });

        // 3x[1,13,6]
        testConvertGrid({
            before: getRegularGridHtml(3, [1, 13, 6]),
            after:
                getRegularTableHtml(2, [1, 12], [12, 1], [100, 8.33], TEST_WIDTH).slice(
                    0,
                    -8,
                ) +
                `<tr>` +
                getTdHtml(1, "(1, 12)", TEST_WIDTH) +
                getTdHtml(11, "", TEST_WIDTH) + // 13 overflowed the row by 1 -> fill up
                `</tr>` +
                getRegularTableHtml(1, 6, 2, 16.67, TEST_WIDTH)
                    .replace(/\(0,/g, `(2,`)
                    .replace(/^<table[^<]*>/, ""),
            title: "should have converted a 3x[1,13,6] grid to an equivalent table (overflowing)",
        });

        // 3x[1,6,13]
        testConvertGrid({
            before: getRegularGridHtml(3, [1, 6, 13]),
            after:
                getRegularTableHtml(
                    3,
                    [1, 6, 12],
                    [12, 2, 1],
                    [100, 16.67, 8.33],
                    TEST_WIDTH,
                ).slice(0, -8) +
                `<tr>` +
                getTdHtml(1, "(2, 12)", TEST_WIDTH) +
                getTdHtml(11, "", TEST_WIDTH) + // 13 overflowed the row by 1 -> fill up
                `</tr></table>`,
            title: "should have converted a 3x[1,6,13] grid to an equivalent table (overflowing)",
        });
    });

    test("convert a single-row irregular grid", async () => {
        // 1x2
        testConvertGrid({
            before: getGridHtml([[8, 4]]),
            after: getTableHtml(
                [
                    [
                        [8, 66.67],
                        [4, 33.33],
                    ],
                ],
                TEST_WIDTH,
            ),
            title: "should have converted a 1x2 irregular grid to an equivalent table",
        });

        // 1x3
        testConvertGrid({
            before: getGridHtml([[2, 3, 7]]),
            after: getTableHtml(
                [
                    [
                        [2, 16.67],
                        [3, 25],
                        [7, 58.33],
                    ],
                ],
                TEST_WIDTH,
            ),
            title: "should have converted a 1x3 grid to an equivalent table",
        });
    });

    test("convert a single-row irregular overflowing grid", async () => {
        // 1x2
        testConvertGrid({
            before: getGridHtml([[8, 5]]),
            after: getTableHtml(
                [
                    [
                        [8, 66.67],
                        [4, 33.33, ""],
                    ],
                    [
                        [5, 41.67, "(0, 1)"],
                        [7, 58.33, ""],
                    ],
                ],
                TEST_WIDTH,
            ),
            title: "should have converted a 1x2 irregular overflowing grid to an equivalent table",
        });

        // 1x3
        testConvertGrid({
            before: getGridHtml([[7, 6, 9]]),
            after: getTableHtml(
                [
                    [
                        [7, 58.33],
                        [5, 41.67, ""],
                    ],
                    [
                        [6, 50, "(0, 1)"],
                        [6, 50, ""],
                    ],
                    [
                        [9, 75, "(0, 2)"],
                        [3, 25, ""],
                    ],
                ],
                TEST_WIDTH,
            ),
            title: "should have converted a 1x3 irregular overflowing grid to an equivalent table",
        });
    });

    test("convert a multi-row irregular grid", async () => {
        // 2x2
        testConvertGrid({
            before: getGridHtml([
                [1, 11],
                [2, 10],
            ]),
            after: getTableHtml(
                [
                    [
                        [1, 8.33],
                        [11, 91.67],
                    ],
                    [
                        [2, 16.67],
                        [10, 83.33],
                    ],
                ],
                TEST_WIDTH,
            ),
            title: "should have converted a 2x2 irregular grid to an equivalent table",
        });

        // 2x[2,3]
        testConvertGrid({
            before: getGridHtml([
                [3, 9],
                [4, 6, 2],
            ]),
            after: getTableHtml(
                [
                    [
                        [3, 25],
                        [9, 75],
                    ],
                    [
                        [4, 33.33],
                        [6, 50],
                        [2, 16.67],
                    ],
                ],
                TEST_WIDTH,
            ),
            title: "should have converted a 2x[2,3] irregular grid to an equivalent table",
        });
    });

    test("convert a multi-row irregular overflowing grid", async () => {
        // 2x2 (both rows overflow)
        testConvertGrid({
            before: getGridHtml([
                [6, 8],
                [7, 9],
            ]),
            after: getTableHtml(
                [
                    [
                        [6, 50],
                        [6, 50, ""],
                    ],
                    [
                        [8, 66.67, "(0, 1)"],
                        [4, 33.33, ""],
                    ],
                    [
                        [7, 58.33, "(1, 0)"],
                        [5, 41.67, ""],
                    ],
                    [
                        [9, 75, "(1, 1)"],
                        [3, 25, ""],
                    ],
                ],
                TEST_WIDTH,
            ),
            title: "should have converted a 2x[1,13] irregular grid to an equivalent table (both rows overflowing)",
        });

        // 2x[2,3] (first row overflows)
        testConvertGrid({
            before: getGridHtml([
                [5, 8],
                [4, 2, 6],
            ]),
            after: getTableHtml(
                [
                    [
                        [5, 41.67],
                        [7, 58.33, ""],
                    ],
                    [
                        [8, 66.67, "(0, 1)"],
                        [4, 33.33, ""],
                    ],
                    [
                        [4, 33.33, "(1, 0)"],
                        [2, 16.67, "(1, 1)"],
                        [6, 50, "(1, 2)"],
                    ],
                ],
                TEST_WIDTH,
            ),
            title: "should have converted a 2x[2,3] irregular grid to an equivalent table (first row overflowing)",
        });

        // 2x[3,2] (second row overflows)
        testConvertGrid({
            before: getGridHtml([
                [4, 2, 6],
                [5, 8],
            ]),
            after: getTableHtml(
                [
                    [
                        [4, 33.33],
                        [2, 16.67],
                        [6, 50],
                    ],
                    [
                        [5, 41.67],
                        [7, 58.33, ""],
                    ],
                    [
                        [8, 66.67, "(1, 1)"],
                        [4, 33.33, ""],
                    ],
                ],
                TEST_WIDTH,
            ),
            title: "should have converted a 2x[3,2] irregular grid to an equivalent table (second row overflowing)",
        });
    });

    test("convert a card to a table", async () => {
        testConvertGrid({
            title: "should have converted a card structure into a table",
            before:
                `<div class="card">` +
                `<div class="card-header">` +
                `<span>HEADER</span>` +
                `</div>` +
                `<div class="card-body">` +
                `<h2 class="card-title">TITLE</h2>` +
                `<small>BODY <img></small>` +
                `</div>` +
                `<div class="card-footer">` +
                `<a href="#" class="btn">FOOTER</a>` +
                `</div>` +
                `</div>`,
            stepFunction: cardToTable,
            after: getRegularTableHtml(3, 1, 12, 100)
                .replace('role="presentation"', 'role="presentation" class="card"')
                .replace(
                    /<td[^>]*>\(0, 0\)<\/td>/,
                    `<td>` +
                        `<table cellspacing="0" cellpadding="0" border="0" width="100%" align="center" ` +
                        `role="presentation" style="width: 100% !important; border-collapse: separate; border-spacing: 0px; text-align: inherit; ` +
                        `font-size: unset; line-height: inherit; height: 100%;"><tr>` +
                        `<td class="card-header"><span>HEADER</span></td>` +
                        `</tr></table></td>`,
                )
                .replace(
                    /<td[^>]*>\(1, 0\)<\/td>/,
                    `<td>` +
                        `<table cellspacing="0" cellpadding="0" border="0" width="100%" align="center" ` +
                        `role="presentation" style="width: 100% !important; border-collapse: separate; border-spacing: 0px; text-align: inherit; ` +
                        `font-size: unset; line-height: inherit; height: 100%;"><tr>` +
                        `<td class="card-body"><h2 class="card-title">TITLE</h2><small>BODY <img></small></td>` +
                        `</tr></table></td>`,
                )
                .replace(
                    /<td[^>]*>\(2, 0\)<\/td>/,
                    `<td>` +
                        `<table cellspacing="0" cellpadding="0" border="0" width="100%" align="center" ` +
                        `role="presentation" style="width: 100% !important; border-collapse: separate; border-spacing: 0px; text-align: inherit; ` +
                        `font-size: unset; line-height: inherit; height: 100%;"><tr>` +
                        `<td class="card-footer"><a href="#" class="btn">FOOTER</a></td>` +
                        `</tr></table></td>`,
                ),
        });
    });

    test("convert a list group to a table", async () => {
        testConvertGrid({
            title: "should have converted a list group structure into a table",
            before:
                `<ul class="list-group list-group-flush">` +
                `<li class="list-group-item">` +
                `<strong>(0, 0)</strong>` +
                `</li>` +
                `<li class="list-group-item a">` +
                `(1, 0)` +
                `</li>` +
                `<li><img></li>` +
                `<li class="list-group-item">` +
                `<strong class="b">(2, 0)</strong>` +
                `</li>` +
                `</ul>`,
            stepFunction: listGroupToTable,
            after: getRegularTableHtml(3, 1, 12, 100)
                .split('style="')
                .join('class="list-group-flush" style="')
                .replace(/<td[^>]*>(\(0, 0\))<\/td>/, "<td><strong>$1</strong></td>")
                .replace(/<td[^>]*>(\(1, 0\))<\/td>/, '<td class="a">$1</td>')
                .replace(
                    /<tr><td[^>]*>(\(2, 0\))<\/td>/,
                    '<img><tr><td><strong class="b">$1</strong></td>',
                ),
        });
    });

    test("do not duplicate the row id on overflowing rows", async () => {
        editable.innerHTML =
            '<div class="container"><div class="row" id="test-row-id">' +
            '<div class="col-8">(0, 0)</div><div class="col-8">(0, 1)</div>' +
            "</div></div>";
        bootstrapToTable(editable);
        expect(editable.querySelectorAll("#test-row-id").length).toBe(1, {
            message: "should have kept the id on a single row only",
        });
    });

    test("ignore whitespace-only text in cards", async () => {
        editable.innerHTML = `<div class="card">\n    <div class="card-body">BODY</div>\n</div>`;
        cardToTable(editable);
        expect(editable.querySelectorAll("tr").length).toBe(2, {
            message: "should not have created a row for whitespace-only text",
        });

        editable.innerHTML = `<div class="card">Loose text<div class="card-body">BODY</div></div>`;
        cardToTable(editable);
        expect(editable.querySelectorAll("tr").length).toBe(4, {
            message: "should have created a row for actual text content",
        });
    });

    test("convert a grid with offsets to a table", async () => {
        testConvertGrid({
            before: '<div class="container"><div class="row"><div class="col-6 offset-4">(0, 0)</div></div>',
            after: getTableHtml(
                [
                    [
                        [4, 33.33, ""],
                        [6, 50, "(0, 0)"],
                        [2, 16.67, ""],
                    ],
                ],
                TEST_WIDTH,
            ),
            title: "should have converted a column with an offset to two columns, then completed the column",
        });

        testConvertGrid({
            before: '<div class="container"><div class="row"><div class="col-6 offset-4">(0, 0)</div><div class="col-6 offset-1">(0, 1)</div></div>',
            after: getTableHtml(
                [
                    [
                        [4, 33.33, ""],
                        [6, 50, "(0, 0)"],
                        [1, 8.33, ""],
                        [1, 8.33, ""],
                    ],
                    [
                        [6, 50, "(0, 1)"],
                        [6, 50, ""],
                    ],
                ],
                TEST_WIDTH,
            ),
            title: "should have converted a column with an offset to two columns, then completed the column (overflowing)",
        });
    });
});

describe("Normalize styles", () => {
    beforeEach(() => {
        editable = document.createElement("div");
    });
    // Test normalizeColors, normalizeRem and formatTables
    test("convert rgb color to hexadecimal", async () => {
        editable.innerHTML = `
        <div style="color: rgb(0, 0, 0);">
            <div class="a" style="padding: 0; background-color:rgb(255,255,255)" width="100%">
                <p style="border: 1px rgb(50, 100,200 ) solid; color: rgb(35, 134, 54);">Test</p>
            </div>
        </div>`;
        normalizeColors(editable);
        expect(editable).toHaveInnerHTML(
            `<div style="color: #000000;">
                <div class="a" style="padding: 0; background-color:#ffffff" width="100%">
                    <p style="border: 1px #3264c8 solid; color: #238636;">Test</p>
                </div>
            </div>`,
            { message: "should have converted several rgb colors to hexadecimal" },
        );
    });

    test("convert rem sizes to px", async () => {
        const testDom = `
        <div style="font-size: 2rem;">
            <div class="a" style="color: #000000; padding: 2.5 rem" width="100%">
                <p style="border: 1.2rem #aaaaaa solid; margin: 3.79rem;">Test</p>
            </div>
        </div>`;
        editable.innerHTML = testDom;
        normalizeRem(editable);
        expect(editable).toHaveInnerHTML(
            `<div style="font-size: 32px;">` +
                `<div class="a" style="color: #000000; padding: 40px" width="100%">` +
                `<p style="border: 19.2px #aaaaaa solid; margin: 60.64px;">Test</p>` +
                `</div>` +
                `</div>`,
            {
                message:
                    "should have converted several rem sizes to px using the default rem size",
            },
        );

        editable.innerHTML = testDom;
        normalizeRem(editable, 20);
        expect(editable).toHaveInnerHTML(
            `<div style="font-size: 40px;">` +
                `<div class="a" style="color: #000000; padding: 50px" width="100%">` +
                `<p style="border: 24px #aaaaaa solid; margin: 75.8px;">Test</p>` +
                `</div>` +
                `</div>`,
            {
                message:
                    "should have converted several rem sizes to px using a set rem size",
            },
        );
    });

    test("move padding from snippet containers to cells", async () => {
        const testTable = `
        <table class="o_mail_snippet_general" style="padding: 10px 20px 30px 40px;">
            <tbody>
                <tr>
                    <td style="padding-top: 1px; padding-right: 2px;">(0, 0, 0)</td>
                    <td style="padding: 3px 4px 5px 6px;">(0, 1, 0)</td>
                    <td style="padding: 7px;">(0, 2, 0)</td>
                    <td style="padding: 8px 9px;">(0, 3, 0)</td>
                    <td style="padding-right: 9.1px;">(0, 4, 0)</td>
                </tr>
                <tr>
                    <td>
                        <table style="padding: 50px 60px 70px 80px;">
                            <tbody>
                                <tr>
                                    <td style="padding: 1px 2px 3px 4px;">(0, 0, 1)</td>
                                    <td style="padding: 5px;">(0, 1, 1)</td>
                                    <td style="padding: 6px 7px;">(0, 2, 1)</td>
                                    <td style="padding-top: 8px; padding-right: 9px;">(0, 3, 1)</td>
                                </tr>
                            </tbody>
                        </table>
                    </td>
                </tr>
                <tr>
                    <td style="padding-left: 9.1px;">(1, 0, 0)</td>
                    <td style="padding: 9px 8px 7px 6px;">(1, 1, 0)</td>
                    <td style="padding: 5px;">(1, 2, 0)</td>
                    <td style="padding: 4px 3px;">(1, 3, 0)</td>
                    <td style="padding-bottom: 2px; padding-right: 1px;">(1, 4, 0)</td>
                </tr>
            </tbody>
        </table>`;

        const expectedTable =
            `<table class="o_mail_snippet_general" style="">` +
            `<tbody>` +
            `<tr>` +
            `<td style="padding-top: 11px; padding-right: 2px; padding-left: 40px;">(0, 0, 0)</td>` + // TL
            `<td style="padding: 13px 4px 5px 6px;">(0, 1, 0)</td>` + // T
            `<td style="padding: 17px 7px 7px;">(0, 2, 0)</td>` + // T
            `<td style="padding: 18px 9px 8px;">(0, 3, 0)</td>` + // T
            `<td style="padding-right: 29.1px; padding-top: 10px;">(0, 4, 0)</td>` + // TR
            `</tr>` +
            `<tr>` +
            `<td style="padding-right: 20px; padding-left: 40px;">` + // LR
            `<table style="">` +
            `<tbody>` +
            `<tr>` +
            `<td style="padding: 51px 2px 73px 84px;">(0, 0, 1)</td>` + // TBL
            `<td style="padding: 55px 5px 75px;">(0, 1, 1)</td>` + // TB
            `<td style="padding: 56px 7px 76px;">(0, 2, 1)</td>` + // TB
            `<td style="padding-top: 58px; padding-right: 69px; padding-bottom: 70px;">(0, 3, 1)</td>` + // TBR
            `</tr>` +
            `</tbody>` +
            `</table>` +
            `</td>` +
            `</tr>` +
            `<tr>` +
            `<td style="padding-left: 49.1px; padding-bottom: 30px;">(1, 0, 0)</td>` + // BL
            `<td style="padding: 9px 8px 37px 6px;">(1, 1, 0)</td>` + // B
            `<td style="padding: 5px 5px 35px;">(1, 2, 0)</td>` + // B
            `<td style="padding: 4px 3px 34px;">(1, 3, 0)</td>` + // B
            `<td style="padding-bottom: 32px; padding-right: 21px;">(1, 4, 0)</td>` + // BR
            `</tr>` +
            `</tbody>` +
            `</table>`;

        // table.o_mail_snippet_general
        editable.innerHTML = testTable;
        formatTables(editable);
        expect(editable).toHaveInnerHTML(expectedTable, {
            message:
                "should have moved the padding from table.o_mail_snippet_general and table in it to their respective cells",
        });
    });

    test("add a tbody to any table that doesn't have one", async () => {
        editable.innerHTML = `<table><tr><td>I don't have a body :'(</td></tr></table>`;
        // unwrap tr (remove <body>)
        const tr = editable.querySelector("tr");
        const body = tr.parentElement;
        body.parentElement.appendChild(tr);
        tr.parentElement.removeChild(body);
        formatTables(editable);
        removeGeneratedMarkers(editable);
        expect(editable).toHaveInnerHTML(
            `<table><tbody style="vertical-align: top;"><tr><td>I don't have a body :'(</td></tr></tbody></table>`,
            { message: "should have added a tbody to a table that didn't have one" },
        );
    });

    test("add number heights to parents of elements with percent heights", async () => {
        editable.innerHTML = `<table><tbody><tr style="height: 100%;"><td>yup</td></tr></tbody></table>`;
        formatTables(editable);
        expect(editable).toHaveInnerHTML(
            `<table><tbody style="height: 0px;"><tr style="height: 100%;"><td>yup</td></tr></tbody></table>`,
            {
                message:
                    "should have added a 0 height to the parent of a 100% height element",
            },
        );

        editable.innerHTML = `<table><tbody style="height: 200px;"><tr style="height: 100%;"><td>yup</td></tr></tbody></table>`;
        formatTables(editable);
        expect(editable).toHaveInnerHTML(
            `<table><tbody style="height: 200px;"><tr style="height: 100%;"><td>yup</td></tr></tbody></table>`,
            {
                message:
                    "should have added a 0 height to the parent of a 100% height element",
            },
        );

        editable.innerHTML = `<table><tbody style="height: 50%;"><tr style="height: 100%;"><td>yup</td></tr></tbody></table>`;
        formatTables(editable);
        expect(editable).toHaveInnerHTML(
            `<table style="height: 0px;"><tbody style="height: 50%;"><tr style="height: 100%;"><td>yup</td></tr></tbody></table>`,
            {
                message:
                    "should have changed the height of the grandparent of a 100% height element",
            },
        );
    });

    test("express align-self with vertical-align on table cells", async () => {
        editable.innerHTML = `<table><tbody><tr><td style="align-self: start;">yup</td></tr></tbody></table>`;
        formatTables(editable);
        expect(editable).toHaveInnerHTML(
            `<table><tbody><tr><td style="align-self: start; vertical-align: top;">yup</td></tr></tbody></table>`,
            { message: "should have added a top vertical alignment" },
        );

        editable.innerHTML = `<table><tbody><tr><td style="align-self: center;">yup</td></tr></tbody></table>`;
        formatTables(editable);
        expect(editable).toHaveInnerHTML(
            `<table><tbody><tr><td style="align-self: center; vertical-align: middle;">yup</td></tr></tbody></table>`,
            { message: "should have added a middle vertical alignment" },
        );

        editable.innerHTML = `<table><tbody><tr><td style="align-self: end;">yup</td></tr></tbody></table>`;
        formatTables(editable);
        expect(editable).toHaveInnerHTML(
            `<table><tbody><tr><td style="align-self: end; vertical-align: bottom;">yup</td></tr></tbody></table>`,
            { message: "should have added a bottom vertical alignment" },
        );
    });
});
describe("Convert snippets and mailing bodies to tables", () => {
    // Test addTables
    beforeEach(() => {
        editable = document.createElement("div");
    });

    test("convert snippets to tables", async () => {
        editable.innerHTML = `<div class="o_mail_snippet_general"><div>Snippet</div></div>`;
        addTables(editable);
        removeGeneratedMarkers(editable);
        expect(editable).toHaveInnerHTML(
            getRegularTableHtml(1, 1, 12, 100)
                .split("style=")
                .join('class="o_mail_snippet_general" style=')
                .replace(
                    /<td[^>]*>\(0, 0\)/,
                    "<td>" +
                        getRegularTableHtml(1, 1, 12, 100).replace(
                            /<td[^>]*>\(0, 0\)/,
                            "<td><div>Snippet</div>",
                        ),
                ),
            {
                message:
                    "should have converted .o_mail_snippet_general to a special table structure with a table in it",
            },
        );

        editable.innerHTML = `
            <div class="o_mail_snippet_general">
                <table><tbody><tr><td>Snippet</td></tr></tbody></table>
            </div>`;
        addTables(editable);
        removeGeneratedMarkers(editable);
        expect(editable).toHaveInnerHTML(
            getRegularTableHtml(1, 1, 12, 100)
                .split("style=")
                .join('class="o_mail_snippet_general" style=')
                .replace(
                    /<td[^>]*>\(0, 0\)/,
                    "<td><table><tbody><tr><td>Snippet</td></tr></tbody></table>",
                ),
            {
                message:
                    "should have converted .o_mail_snippet_general to a special table structure, keeping the table in it",
            },
        );
    });

    test("convert mailing bodies to tables", async () => {
        editable.innerHTML = `<div class="o_layout"><div>Mailing</div></div>`;
        addTables(editable);
        removeGeneratedMarkers(editable);
        expect(editable).toHaveInnerHTML(
            getRegularTableHtml(1, 1, 12, 100)
                .split("style=")
                .join('class="o_layout" style=')
                .replace(" font-size: unset; line-height: inherit;", "") // o_layout keeps those default values
                .replace(
                    /<td[^>]*>\(0, 0\)/,
                    "<td>" +
                        getRegularTableHtml(1, 1, 12, 100).replace(
                            /<td[^>]*>\(0, 0\)/,
                            "<td><div>Mailing</div>",
                        ),
                ),
            {
                message:
                    "should have converted .o_layout to a special table structure with a table in it",
            },
        );

        editable.innerHTML = `
            <div class="o_layout">
                <table><tbody><tr><td>Mailing</td></tr></tbody></table>
            </div>`;
        addTables(editable);
        removeGeneratedMarkers(editable);
        expect(editable).toHaveInnerHTML(
            getRegularTableHtml(1, 1, 12, 100)
                .split("style=")
                .join('class="o_layout" style=')
                .replace(" font-size: unset; line-height: inherit;", "") // o_layout keeps those default values
                .replace(
                    /<td[^>]*>\(0, 0\)/,
                    "<td><table><tbody><tr><td>Mailing</td></tr></tbody></table>",
                ),
            {
                message:
                    "should have converted .o_layout to a special table structure, keeping the table in it",
            },
        );
    });
});
describe("Convert classes to inline styles", () => {
    // Test classToStyle

    let styleEl, styleSheet;

    beforeEach(() => {
        editable = document.createElement("div");

        styleEl = document.createElement("style");
        styleEl.title = "test-stylesheet";
        document.head.appendChild(styleEl);
        styleSheet = [...document.styleSheets].find(
            (sheet) => sheet.title === "test-stylesheet",
        );
    });

    test("convert Bootstrap classes to inline styles", async () => {
        enableTransitions();
        editable.innerHTML = `
            <div class="container"><div class="row"><div class="col">Hello</div></div></div>`;
        getFixture().append(editable); // editable needs to be in the DOM to compute its dynamic styles.

        const borderColor = `rgb(255, 0, 0)`;
        styleSheet.insertRule(
            `div {
                border-color: ${borderColor} !important;
            }`,
            0,
        );

        classToStyle(editable, getCSSRules(editable.ownerDocument));
        // Some positional properties (eg., padding-right, margin-left) are not
        // concatenated (eg., as padding, margin) because they were defined with
        // variables (var) or calculated (calc).
        // Note: computed border/border-radius values are no longer force
        // applied on every node: only grouped styles that a matched rule
        // defines through var()/calc() are completed with computed values.
        const containerStyle = `margin: 0px auto; box-sizing: border-box; max-width: 1320px; padding-left: 16px; padding-right: 16px; width: 100%; border-color: ${borderColor};`;
        const rowStyle = `box-sizing: border-box; margin-left: -16px; margin-right: -16px; margin-top: 0px; border-color: ${borderColor};`;
        const colStyle = `box-sizing: border-box; margin-top: 0px; padding-left: 16px; padding-right: 16px; max-width: 100%; width: 100%; border-color: ${borderColor};`;
        expect(editable).toHaveInnerHTML(
            `<div class="container" style="${containerStyle}" width="100%">` +
                `<div class="row" style="${rowStyle}">` +
                `<div class="col" style="${colStyle}" width="100%">Hello</div></div></div>`,
            {
                message:
                    "should have converted the classes of a simple Bootstrap grid to inline styles",
            },
        );
        styleSheet.deleteRule(0);
    });

    test("strip theme color classes after inlining their styles", async () => {
        const bgColor = "rgb(17, 24, 39)";
        const style = document.createElement("style");
        style.textContent = `.bg-o-color-5 { background-color: ${bgColor} !important; }`;
        const fixture = getFixture();
        fixture.append(style);

        editable.innerHTML = `<div class="bg-o-color-5 keep-me">Hello</div>`;
        fixture.append(editable);

        classToStyle(editable, getCSSRules(editable.ownerDocument));

        const block = editable.querySelector(".keep-me");
        expect(block).toHaveStyle({ backgroundColor: bgColor });
        expect(block).not.toHaveClass("bg-o-color-5");
    });

    test("simplify border/margin/padding styles", async () => {
        // border-radius
        styleSheet.insertRule(
            `
            .test-border-radius {
                border-top-right-radius: 10%;
                border-bottom-right-radius: 20%;
                border-bottom-left-radius: 30%;
                border-top-left-radius: 40%;
            }
        `,
            0,
        );
        editable.innerHTML = `<div class="test-border-radius"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            // top-left top-right bottom-right bottom-left — each distinct corner
            // must be preserved (this used to collapse to a single 30%).
            `<div class="test-border-radius" style="border-radius:40% 10% 20% 30%;box-sizing:border-box;"></div>`,
            {
                message:
                    "should have converted border-[position]-radius styles (from class) to border-radius",
            },
        );
        styleSheet.deleteRule(0);

        // convert all positional styles to a style in the form `property: a b c d`

        styleSheet.insertRule(
            `
            .test-border {
                border-top-style: dotted;
                border-right-style: dashed;
                border-left-style: solid;
            }
        `,
            0,
        );
        editable.innerHTML = `<div class="test-border"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div class="test-border" style="border-style:dotted dashed none solid;box-sizing:border-box;"></div>`,
            {
                message:
                    "should have converted border-[position]-style styles (from class) to border-style",
            },
        );
        styleSheet.deleteRule(0);

        styleSheet.insertRule(
            `
            .test-margin {
                margin-right: 20px;
                margin-bottom: 30px;
                margin-left: 40px;
            }
        `,
            0,
        );
        editable.innerHTML = `<div class="test-margin"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div class="test-margin" style="margin:0 20px 30px 40px;box-sizing:border-box;"></div>`,
            {
                message:
                    "should have converted margin-[position] styles (from class) to margin",
            },
        );
        styleSheet.deleteRule(0);

        styleSheet.insertRule(
            `
            .test-padding {
                padding-top: 10px;
                padding-bottom: 30px;
                padding-left: 40px;
            }
        `,
            0,
        );
        editable.innerHTML = `<div class="test-padding"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div class="test-padding" style="padding:10px 0 30px 40px;box-sizing:border-box;"></div>`,
            {
                message:
                    "should have converted padding-[position] styles (from class) to padding",
            },
        );
        styleSheet.deleteRule(0);

        // convert all positional styles to a style in the form `property: a`

        styleSheet.insertRule(
            `
            .test-border-uniform {
                border-top-style: dotted;
                border-right-style: dotted;
                border-bottom-style: dotted;
                border-left-style: dotted;
            }
        `,
            0,
        );
        editable.innerHTML = `<div class="test-border-uniform"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div class="test-border-uniform" style="border-style:dotted;box-sizing:border-box;"></div>`,
            {
                message:
                    "should have converted uniform border-[position]-style styles (from class) to border-style",
            },
        );
        styleSheet.deleteRule(0);

        styleSheet.insertRule(
            `
            .test-margin-uniform {
                margin-top: 10px;
                margin-right: 10px;
                margin-bottom: 10px;
                margin-left: 10px;
            }
        `,
            0,
        );
        editable.innerHTML = `<div class="test-margin-uniform"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div class="test-margin-uniform" style="margin:10px;box-sizing:border-box;"></div>`,
            {
                message:
                    "should have converted uniform margin-[position] styles (from class) to margin",
            },
        );
        styleSheet.deleteRule(0);

        styleSheet.insertRule(
            `
            .test-padding-uniform {
                padding-top: 10px;
                padding-right: 10px;
                padding-bottom: 10px;
                padding-left: 10px;
            }
        `,
            0,
        );
        editable.innerHTML = `<div class="test-padding-uniform"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div class="test-padding-uniform" style="padding:10px;box-sizing:border-box;"></div>`,
            {
                message:
                    "should have converted uniform padding-[position] styles (from class) to padding",
            },
        );
        styleSheet.deleteRule(0);

        // do not convert positional styles that include an "inherit" value

        styleSheet.insertRule(
            `
            .test-border-inherit {
                border-top-style: dotted;
                border-right-style: dashed;
                border-bottom-style: inherit;
                border-left-style: solid;
            }
        `,
            0,
        );
        editable.innerHTML = `<div class="test-border-inherit"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div class="test-border-inherit" style="box-sizing:border-box;border-left-style:solid;border-bottom-style:inherit;border-right-style:dashed;border-top-style:dotted;"></div>`,
            {
                message:
                    "should not have converted border-[position]-style styles (from class) to border-style as they include an inherit",
            },
        );
        styleSheet.deleteRule(0);

        styleSheet.insertRule(
            `
            .test-margin-inherit {
                margin-top: 10px;
                margin-right: inherit;
                margin-bottom: 30px;
                margin-left: 40px;
            }
        `,
            0,
        );
        editable.innerHTML = `<div class="test-margin-inherit"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div class="test-margin-inherit" style="box-sizing:border-box;margin-left:40px;margin-bottom:30px;margin-right:inherit;margin-top:10px;"></div>`,
            {
                message:
                    "should not have converted margin-[position] styles (from class) to margin as they include an inherit",
            },
        );
        styleSheet.deleteRule(0);

        styleSheet.insertRule(
            `
            .test-padding-inherit {
                padding-top: 10px;
                padding-right: 20px;
                padding-bottom: inherit;
                padding-left: 40px;
            }
        `,
            0,
        );
        editable.innerHTML = `<div class="test-padding-inherit"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div class="test-padding-inherit" style="box-sizing:border-box;padding-left:40px;padding-bottom:inherit;padding-right:20px;padding-top:10px;"></div>`,
            {
                message:
                    "should have converted padding-[position] styles (from class) to padding as they include an inherit",
            },
        );
        styleSheet.deleteRule(0);

        // do not convert positional styles that include an "initial" value

        // note: `border: initial` is automatically removed (tested in "remove
        // unsupported styles")
        styleSheet.insertRule(
            `
            .test-margin-initial {
                margin-top: initial;
                margin-right: 20px;
                margin-bottom: 30px;
                margin-left: 40px;
            }
        `,
            0,
        );
        editable.innerHTML = `<div class="test-margin-initial"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div class="test-margin-initial" style="box-sizing:border-box;margin-left:40px;margin-bottom:30px;margin-right:20px;margin-top:initial;"></div>`,
            {
                message:
                    "should not have converted margin-[position] styles (from class) to margin as they include an initial",
            },
        );
        styleSheet.deleteRule(0);

        styleSheet.insertRule(
            `
            .test-padding-initial {
                padding-top: 10px;
                padding-right: 20px;
                padding-bottom: 30px;
                padding-left: initial;
            }
        `,
            0,
        );
        editable.innerHTML = `<div class="test-padding-initial"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div class="test-padding-initial" style="box-sizing:border-box;padding-left:initial;padding-bottom:30px;padding-right:20px;padding-top:10px;"></div>`,
            {
                message:
                    "should not have converted padding-[position] styles (from class) to padding as they include an initial",
            },
        );
        styleSheet.deleteRule(0);

        // @todo to adapt when hoot has a better way to remove it
    });

    test("remove unsupported styles", async () => {
        // text-decoration-[prop]
        styleSheet.insertRule(
            `
            .test-decoration {
                text-decoration-line: underline;
                text-decoration-color: red;
                text-decoration-style: solid;
                text-decoration-thickness: 10px;
            }
        `,
            0,
        );
        editable.innerHTML = `<div class="test-decoration"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div class="test-decoration" style="text-decoration:underline;box-sizing:border-box;"></div>`,
            {
                message:
                    "should have removed all text-decoration-[prop] styles (from class) and kept a simple text-decoration",
            },
        );
        styleSheet.deleteRule(0);

        // border[\w-]*: initial
        styleSheet.insertRule(
            `
            .test-border-initial {
                border-top-style: dotted;
                border-right-style: dashed;
                border-bottom-style: double;
                border-left-style: initial;
            }
        `,
            0,
        );
        editable.innerHTML = `<div class="test-border-initial"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div class="test-border-initial" style="box-sizing:border-box;border-bottom-style:double;border-right-style:dashed;border-top-style:dotted;"></div>`,
            { message: "should have removed border initial" },
        );
        styleSheet.deleteRule(0);

        // display: block
        styleSheet.insertRule(
            `
            .test-block {
                display: block;
            }
        `,
            0,
        );
        editable.innerHTML = `<div class="test-block"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div class="test-block" style="box-sizing:border-box;"></div>`,
            { message: "should have removed display block" },
        );
        styleSheet.deleteRule(0);

        // !important
        styleSheet.insertRule(
            `
            .test-unimportant-color {
                color: blue;
            }
        `,
            0,
        );
        editable.innerHTML = `<div class="test-unimportant-color"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div class="test-unimportant-color" style="box-sizing:border-box;color:blue;"></div>`,
            { message: "should have converted a simple color" },
        );
        styleSheet.insertRule(
            `
            .test-important-color {
                color: red !important;
            }
        `,
            0,
        );
        editable.innerHTML = `<div class="test-important-color test-unimportant-color"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div class="test-important-color test-unimportant-color" style="box-sizing:border-box;color:red;"></div>`,
            {
                message:
                    "should have converted an important color and removed the !important",
            },
        );
        styleSheet.deleteRule(0);
        styleSheet.deleteRule(0);

        // animation
        styleSheet.insertRule(
            `
            .test-animation {
                animation: example 5s linear 2s infinite alternate;
            }
        `,
            0,
        );
        editable.innerHTML = `<div class="test-animation"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div class="test-animation" style="box-sizing:border-box;"></div>`,
            { message: "should have removed animation style" },
        );
        styleSheet.deleteRule(0);
        styleSheet.insertRule(
            `
            .test-animation-specific {
                animation-name: example;
                animation-duration: 5s;
                animation-timing-function: linear;
                animation-delay: 2s;
                animation-iteration-count: infinite;
                animation-direction: alternate;
            }
        `,
            0,
        );
        editable.innerHTML = `<div class="test-animation-specific"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div class="test-animation-specific" style="box-sizing:border-box;"></div>`,
            { message: "should have removed all specific animation styles" },
        );
        styleSheet.deleteRule(0);

        // flex
        styleSheet.insertRule(
            `
            .test-flex {
                flex: 0 1 auto;
                flex-flow: column wrap;
            }
        `,
            0,
        );
        editable.innerHTML = `<div class="test-flex"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div class="test-flex" style="box-sizing:border-box;"></div>`,
            { message: "should have removed all flex styles" },
        );
        styleSheet.deleteRule(0);
        styleSheet.insertRule(
            `
            .test-flex-specific {
                display: flex;
                flex-direction: row;
                flex-wrap: wrap;
                flex-basis: auto;
                flex-shrink: 3;
                flex-grow: 4;
            }
        `,
            0,
        );
        editable.innerHTML = `<div class="test-flex-specific"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div class="test-flex-specific" style="box-sizing:border-box;"></div>`,
            { message: "should have removed all specific flex styles" },
        );
        styleSheet.deleteRule(0);

        // @todo to adapt when hoot has a better way to remove it
    });

    test("give .o_layout the styles of the body", async () => {
        const iframe = document.createElement("IFRAME");

        getFixture().append(iframe);
        const iframeEditable = document.createElement("div");
        iframe.contentDocument.body.append(iframeEditable);
        const styleEl = document.createElement("style");
        styleEl.type = "text/css";
        styleEl.title = "test-stylesheet";
        iframe.contentDocument.head.appendChild(styleEl);
        const styleSheet = [...iframe.contentDocument.styleSheets].find(
            (sheet) => sheet.title === "test-stylesheet",
        );
        const borderColor = `rgb(255, 0, 0)`;
        styleSheet.insertRule(
            `
            body {
                background-color: red;
                color: white;
                direction: rtl;
                font-size: 50px;
                div {
                    border-color: ${borderColor} !important;
                }
            }
        `,
            0,
        );
        iframeEditable.innerHTML = `<div class="o_layout" style="padding: 50px;">Test</div>`;
        classToStyle(iframeEditable, getCSSRules(iframeEditable.ownerDocument));
        expect(iframeEditable).toHaveInnerHTML(
            `<div class="o_layout" style="box-sizing:border-box;border-left-color:${borderColor};border-bottom-color:${borderColor};border-right-color:${borderColor};border-top-color:${borderColor};font-size:50px;direction:rtl;color:white;background-color:red;padding: 50px;">Test</div>`,
            { message: "should have given all styles of body to .o_layout" },
        );
        styleSheet.deleteRule(0);
    });

    test("convert classes to styles, preserving specificity", async () => {
        styleSheet.insertRule(
            `
            div.test-color {
                color: green;
            }
        `,
            0,
        );
        styleSheet.insertRule(
            `
            .test-color {
                color: red;
            }
        `,
            1,
        );
        styleSheet.insertRule(
            `
            .test-color {
                color: blue;
            }
        `,
            2,
        );

        editable.innerHTML = `<span class="test-color"></span>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<span class="test-color" style="box-sizing:border-box;color:blue;"></span>`,
            { message: "should have prioritized the last defined style" },
        );

        editable.innerHTML = `<div class="test-color"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div class="test-color" style="box-sizing:border-box;color:green;"></div>`,
            { message: "should have prioritized the more specific style" },
        );

        editable.innerHTML = `<div class="test-color" style="color: yellow;"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div class="test-color" style="box-sizing:border-box;color: yellow;"></div>`,
            { message: "should have prioritized the inline style" },
        );

        styleSheet.insertRule(
            `
            .test-color {
                color: black !important;
            }
        `,
            0,
        );
        editable.innerHTML = `<div class="test-color"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div class="test-color" style="box-sizing:border-box;color:black;"></div>`,
            { message: "should have prioritized the important style" },
        );

        // @todo to adapt when hoot has a better way to remove it
    });

    test("do not force computed grouped styles without dynamic values", async () => {
        enableTransitions();
        styleSheet.insertRule(
            `
            .test-no-bloat {
                color: blue;
            }
        `,
            0,
        );
        editable.innerHTML = `<div class="test-no-bloat">Hello</div>`;
        getFixture().append(editable); // Attached: computed styles are resolvable.
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div class="test-no-bloat" style="box-sizing:border-box;color:blue;">Hello</div>`,
            {
                message:
                    "should not have baked computed border/margin/padding/border-radius values into the inline style",
            },
        );
        styleSheet.deleteRule(0);
    });

    test("force computed values for grouped styles defined with css variables", async () => {
        enableTransitions();
        styleSheet.insertRule(
            `
            .test-var-border {
                --test-border-width: 3px;
                border-width: var(--test-border-width);
                border-style: solid;
                border-color: blue;
            }
        `,
            0,
        );
        editable.innerHTML = `<div class="test-var-border">Hello</div>`;
        getFixture().append(editable); // Attached: computed styles are resolvable.
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        const node = editable.firstElementChild;
        expect(node.style.borderTopWidth).toBe("3px", {
            message: "should have inlined the computed value of the var() border width",
        });
        expect(node.style.borderTopStyle).toBe("solid", {
            message: "should have kept the rule-provided border style",
        });
        styleSheet.deleteRule(0);
    });

    test("strip inline flex styles", async () => {
        styleSheet.insertRule(
            `
            .test-inline-flex {
                color: red;
            }
        `,
            0,
        );
        editable.innerHTML = `<div class="test-inline-flex" style="display: flex; flex-grow: 1; text-align: center;"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div class="test-inline-flex" style="box-sizing:border-box;color:red; text-align: center;"></div>`,
            { message: "should have removed the inline flex declarations" },
        );
        styleSheet.deleteRule(0);
    });

    test("compute selector specificity per the CSS specification", async () => {
        // One id beats any number of classes.
        styleSheet.insertRule(`#test-spec-id { color: red; }`, 0);
        styleSheet.insertRule(
            `.tsc1.tsc2.tsc3.tsc4.tsc5.tsc6.tsc7.tsc8.tsc9.tsc10 { color: blue; }`,
            1,
        );
        editable.innerHTML = `<div id="test-spec-id" class="tsc1 tsc2 tsc3 tsc4 tsc5 tsc6 tsc7 tsc8 tsc9 tsc10"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div id="test-spec-id" class="tsc1 tsc2 tsc3 tsc4 tsc5 tsc6 tsc7 tsc8 tsc9 tsc10" style="box-sizing:border-box;color:red;"></div>`,
            { message: "should have prioritized one id over ten classes" },
        );
        styleSheet.deleteRule(0);
        styleSheet.deleteRule(0);

        // Pseudo-classes count at the class level, not the type level.
        styleSheet.insertRule(`div:first-child { color: green; }`, 0);
        styleSheet.insertRule(`.test-spec-pseudo { color: blue; }`, 1);
        editable.innerHTML = `<div class="test-spec-pseudo"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div class="test-spec-pseudo" style="box-sizing:border-box;color:green;"></div>`,
            {
                message:
                    "should have prioritized the (0, 1, 1) pseudo-class selector over the (0, 1, 0) class",
            },
        );
        styleSheet.deleteRule(0);
        styleSheet.deleteRule(0);

        // :not() itself counts for nothing; only its argument counts. Both
        // selectors are (0, 1, 1): the later one must win.
        styleSheet.insertRule(`div:not(.absent) { color: purple; }`, 0);
        styleSheet.insertRule(`div.test-spec-not { color: orange; }`, 1);
        editable.innerHTML = `<div class="test-spec-not"></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div class="test-spec-not" style="box-sizing:border-box;color:orange;"></div>`,
            {
                message:
                    "should have resolved the specificity tie between :not() and a class by document order",
            },
        );
        styleSheet.deleteRule(0);
        styleSheet.deleteRule(0);
    });

    test("only collect email-compatible css rules", async () => {
        styleSheet.insertRule(
            `@media (min-width: 1200px) { .test-media-desktop { color: red; } }`,
            0,
        );
        styleSheet.insertRule(
            `@media (min-width: 768px) and (max-width: 991.98px) { .test-media-tablet { color: blue; } }`,
            1,
        );
        styleSheet.insertRule(
            `@media (max-width: 575.98px) { .test-media-mobile { color: green; } }`,
            2,
        );
        styleSheet.insertRule(
            `@media screen { .test-media-screen { color: purple; } }`,
            3,
        );
        styleSheet.insertRule(
            `@media print { .test-media-print { color: black; } }`,
            4,
        );
        styleSheet.insertRule(
            `.test-nested-parent { .test-nested-child { color: orange; } }`,
            5,
        );
        styleSheet.insertRule(`.test-visited:visited { color: yellow; }`, 6);
        styleSheet.insertRule(`.test-checked:checked { color: yellow; }`, 7);
        styleSheet.insertRule(`.test-disabled:disabled { color: yellow; }`, 8);

        const selectors = new Set(
            getCSSRules(editable.ownerDocument).map((rule) => rule.selector),
        );
        // Unbounded desktop min-width rules apply to emails.
        expect(selectors.has(".test-media-desktop")).toBe(true);
        // Bounded (tablet-only) ranges and mobile-only rules do not.
        expect(selectors.has(".test-media-tablet")).toBe(false);
        expect(selectors.has(".test-media-mobile")).toBe(false);
        // Unconditional screen rules apply, print rules do not.
        expect(selectors.has(".test-media-screen")).toBe(true);
        expect(selectors.has(".test-media-print")).toBe(false);
        // Nested rules are resolved against their parent selectors.
        expect(selectors.has(".test-nested-parent .test-nested-child")).toBe(true);
        // Interaction-state pseudo-classes cannot apply in an email.
        expect([...selectors].some((sel) => sel.includes(":visited"))).toBe(false);
        expect([...selectors].some((sel) => sel.includes(":checked"))).toBe(false);
        expect([...selectors].some((sel) => sel.includes(":disabled"))).toBe(false);

        for (let i = 0; i < 9; i++) {
            styleSheet.deleteRule(0);
        }
    });

    test("Correct border attributes for outlook", async () => {
        styleSheet.insertRule(
            `
            .test-border-zero {
                border-bottom-width: 0px;
                border-left-width: 0px;
                border-right-width: 0px;
                border-top-width: 0px;
                border-style: solid;
            }
        `,
            0,
        );

        styleSheet.insertRule(
            `
            .test-border-one {
                border-bottom-width: 1px;
                border-left-width: 1px;
                border-right-width: 1px;
                border-top-width: 1px;
                border-style: solid;
            }
        `,
            1,
        );

        editable.innerHTML = `<div><div class="test-border-zero"></div></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div><div class="test-border-zero" style="border-style:none;box-sizing:border-box;border-top-width:0px;border-right-width:0px;border-left-width:0px;border-bottom-width:0px;"></div></div>`,
            { message: "Should change border-style to none" },
        );

        editable.innerHTML = `<div><div class="test-border-one"></div></div>`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<div><div class="test-border-one" style="border-style:solid;box-sizing:border-box;border-top-width:1px;border-right-width:1px;border-left-width:1px;border-bottom-width:1px;"></div></div>`,
            { message: "Should keep border style solid" },
        );
    });

    test("preserve asymmetric border-radius corners when inlining (regression: bug E)", async () => {
        // Distinct per-corner radii, reached via calc() so the dynamic-substyle
        // path materialises the four computed corner longhands (a plain
        // shorthand would be merged by the CSSOM before classToStyle sees it).
        editable.innerHTML = `<div class="bubble">x</div>`;
        getFixture().append(editable);
        styleSheet.insertRule(
            `.bubble { border-radius: calc(4px) calc(8px) calc(12px) calc(16px); }`,
            0,
        );
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        const div = editable.querySelector("div");
        // The shorthand collapse must keep every corner. The current code copies
        // border-bottom-left-radius onto all four corners, so a card authored
        // with distinct corners renders with a single (bottom-left) radius.
        expect(div.style.borderTopLeftRadius).toBe("4px", {
            message: "top-left radius must survive inlining",
        });
        expect(div.style.borderTopRightRadius).toBe("8px", {
            message: "top-right radius must survive inlining",
        });
        expect(div.style.borderBottomRightRadius).toBe("12px", {
            message: "bottom-right radius must survive inlining",
        });
        expect(div.style.borderBottomLeftRadius).toBe("16px", {
            message: "bottom-left radius must survive inlining",
        });
        styleSheet.deleteRule(0);
    });

    test("flex alignment survives inlining so formatTables can map it (regression: bug G)", async () => {
        // align-items on a flex row must translate to vertical-align on the row.
        // The flex-strip in classToStyle must not swallow the flex-* keyword
        // before formatTables gets to read it.
        editable.innerHTML = `<table><tbody><tr style="align-items: flex-start;"><td>x</td></tr></tbody></table>`;
        getFixture().append(editable);
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        formatTables(editable);
        const tr = editable.querySelector("tr");
        expect(tr.style.verticalAlign).toBe("top", {
            message: "align-items:flex-start must become vertical-align:top",
        });

        editable.innerHTML = `<table><tbody><tr style="align-items: flex-end;"><td>x</td></tr></tbody></table>`;
        getFixture().append(editable);
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        formatTables(editable);
        expect(editable.querySelector("tr").style.verticalAlign).toBe("bottom", {
            message: "align-items:flex-end must become vertical-align:bottom",
        });
    });
});

describe("Properly add MSO conditions", () => {
    test("Create mso properly", async () => {
        expect(createMso("<div>abcde</div>").nodeValue).toEqual(
            `[if mso]><div>abcde</div><![endif]`,
            { message: "Should wrap the content in mso condition" },
        );

        expect(
            createMso("<div>ef<!--[if mso]><div>abcd</div><![endif]-->gh</div>")
                .nodeValue,
        ).toEqual(`[if mso]><div>ef<div>abcd</div>gh</div><![endif]`, {
            message: "Should wrap the content inside one mso condition",
        });

        expect(
            createMso("<div>ef<!--[if !mso]><div>abcd</div><![endif]-->gh</div>")
                .nodeValue,
        ).toEqual(`[if mso]><div>efgh</div><![endif]`, {
            message: "Should remove nested mso hide condition",
        });
    });
});

describe("Should not convert blacklisted class to inline styles", () => {
    let styleEl, styleSheet;

    beforeEach(() => {
        editable = document.createElement("div");

        styleEl = document.createElement("style");
        styleEl.type = "text/css";
        styleEl.title = "test-stylesheet";
        document.head.appendChild(styleEl);
        styleSheet = [...document.styleSheets].find(
            (sheet) => sheet.title === "test-stylesheet",
        );
    });

    test("should not convert blacklisted class to inline style", async () => {
        editable.innerHTML = `
            <a contenteditable="false" href="#" class="o_mail_redirect">@Marc Demo</a> Testing!`;

        classToStyle(editable, getCSSRules(editable.ownerDocument));

        expect(editable).toHaveInnerHTML(
            `<a contenteditable="false" href="#" class="o_mail_redirect" style="text-decoration: none; padding: 0rem 0.15rem; margin: 0rem 0.025rem; box-sizing: border-box; overflow-wrap: unset;">@Marc Demo</a> Testing!`,
            {
                message: "blacklisted class styles should remain unconverted",
            },
        );
    });

    test("should convert styles from class using !important even if blacklisted class is present", async () => {
        styleSheet.insertRule(`
            .test-style {
                background-color: yellow !important;
            }
        `);
        editable.innerHTML = `<a contenteditable="false" href="#" class="o_mail_redirect test-style">@Marc Demo</a> Testing!`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<a contenteditable="false" href="#" class="o_mail_redirect test-style" style="text-decoration: none; padding: 0rem 0.15rem; margin: 0rem 0.025rem; box-sizing: border-box; background-color: yellow; overflow-wrap: unset;"> @Marc Demo </a> Testing!`,
            {
                message:
                    "styles marked !important should override blacklisted class restrictions",
            },
        );
    });

    test("should not convert style of class having less specificity when overridden by a blacklisted class", async () => {
        styleSheet.insertRule(`
            .test-color {
                color: black;
            }
        `);
        editable.innerHTML = `<a contenteditable="false" href="#" class="o_mail_redirect test-color">@Marc Demo</a> Testing!`;
        classToStyle(editable, getCSSRules(editable.ownerDocument));
        expect(editable).toHaveInnerHTML(
            `<a contenteditable="false" href="#" class="o_mail_redirect test-color" style="text-decoration: none; padding: 0rem 0.15rem; margin: 0rem 0.025rem; box-sizing: border-box; overflow-wrap: unset;"> @Marc Demo </a> Testing!`,
            {
                message:
                    "should ignore styles from lower specificity class in favor of blacklisted class",
            },
        );
    });
});

describe("Convert to inline (full pipeline)", () => {
    test("toInline is idempotent on its own output", async () => {
        editable = document.createElement("div");
        editable.style.setProperty("width", TEST_WIDTH + "px");
        getFixture().append(editable);
        editable.innerHTML =
            '<div class="o_layout">' +
            '<div class="container"><div class="row">' +
            '<div class="col-8"><p>Hello there</p></div>' +
            '<div class="col-4"><a href="#" class="btn">Click me</a></div>' +
            "</div></div>" +
            '<div class="card"><div class="card-body">Card body</div></div>' +
            "</div>";
        const cssRules = getCSSRules(document);
        await toInline(editable, cssRules);
        const inlinedOnce = editable.innerHTML;
        await toInline(editable, cssRules);
        // Compare raw innerHTML: mso conditional comments matter here.
        expect(editable.innerHTML).toBe(inlinedOnce, {
            message: "a second run on the converted output should change nothing",
        });
    });
});
