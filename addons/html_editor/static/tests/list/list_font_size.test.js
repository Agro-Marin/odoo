import { ListPlugin } from "@html_editor/main/list/list_plugin";
import { nodeSize } from "@html_editor/utils/position";
import { before, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";

import { testEditor } from "../_helpers/editor.js";
import { loadTestFont, pinFont, pinRootFontSize } from "../_helpers/font.js";
import { unformat } from "../_helpers/format.js";
import {
    setFontSize,
    splitBlock,
    toggleOrderedList,
    toggleUnorderedList,
} from "../_helpers/user_actions.js";
import { execCommand } from "../_helpers/userCommands.js";

before(loadTestFont);

/**
 * Pin the ``::marker`` width that {@link ListPlugin#adjustListPadding} reads.
 *
 * That width is produced by the browser's font rasterizer, so it is NOT stable
 * across environments: the very same markup measures 19px on Chromium 149 and
 * 20px on Chrome 150, and different again under another default font. Tests
 * that hard-coded the resulting ``padding-inline-start`` therefore encoded one
 * machine's rasterizer, and broke on any other — which is exactly what
 * happened here.
 *
 * Stubbing the single measured input makes the padding arithmetic
 * (``round(width) * (UL ? 2 : 1)``, applied only when it exceeds
 * ``2 * root font-size``) deterministic and genuinely assertable, while
 * production keeps measuring the real marker.
 *
 * @param {number} width marker width in px to report for every list item
 */
function pinMarkerWidth(width) {
    patchWithCleanup(ListPlugin.prototype, {
        measureMarkerWidth() {
            return width;
        },
    });
}

test("should apply font-size to completely selected list item (1)", async () => {
    // 60px marker on an OL -> round(60) * 1 = 60px, above the 28px default
    // (`:root` is pinned to 14px below, so the default is 2 * 14).
    pinMarkerWidth(60);
    await testEditor({
        styleContent: pinRootFontSize("14px"),
        contentBefore: "<ol><li>[abc]</li><li>def</li></ol>",
        stepFunction: setFontSize("56px"),
        contentAfter: `<ol style="padding-inline-start: 60px;"><li style="font-size: 56px;">[abc]</li><li>def</li></ol>`,
    });
});

test("should apply font-size to completely selected list item (2)", async () => {
    // Both the outer and the nested OL measure the same pinned marker, so both
    // receive the same padding — the point of the test is that the nested list
    // is adjusted too, not the specific width.
    pinMarkerWidth(69);
    await testEditor({
        styleContent: pinRootFontSize("14px"),
        contentBefore: unformat(`
            <ol>
                <li><p>[abc</p>
                    <ol>
                        <li>def</li>
                    </ol>
                </li>
                <li>ghi]</li>
            </ol>
        `),
        stepFunction: setFontSize("64px"),
        contentAfter: unformat(`
            <ol style="padding-inline-start: 69px;">
                <li style="font-size: 64px;"><p>[abc</p>
                    <ol class="o_default_font_size" style="padding-inline-start: 69px;">
                        <li style="font-size: 64px;">def</li>
                    </ol>
                </li>
                <li style="font-size: 64px;">ghi]</li>
            </ol>
        `),
    });
});

test("should apply font-size to completely selected multiple list items", async () => {
    await testEditor({
        contentBefore: "<ul><li>[abc</li><li>def]</li></ul>",
        stepFunction: (editor) =>
            execCommand(editor, "formatFontSizeClassName", { className: "h2-fs" }),
        contentAfter: '<ul><li class="h2-fs">[abc</li><li class="h2-fs">def]</li></ul>',
    });
});

test("should apply font size to a fully selected list item with trailing empty line (1)", async () => {
    // 19px marker on a UL -> round(19) * 2 = 38px, above the 28px default
    // (`:root` is pinned to 14px below, so the default is 2 * 14).
    pinMarkerWidth(19);
    await testEditor({
        styleContent: pinRootFontSize("14px"),
        contentBefore: "<ul><li>[abc</li><li>]<br></li></ul>",
        stepFunction: setFontSize("56px"),
        contentAfter:
            '<ul style="padding-inline-start: 38px;"><li style="font-size: 56px;">[abc</li><li style="font-size: 56px;">]<br></li></ul>',
    });
});

test("should apply font size to a fully selected list item with trailing empty line (2)", async () => {
    pinMarkerWidth(19);
    await testEditor({
        styleContent: pinRootFontSize("14px"),
        contentBefore: "<ul><li>[abc</li><li><br>]<br></li></ul>",
        stepFunction: setFontSize("56px"),
        contentAfter:
            '<ul style="padding-inline-start: 38px;"><li style="font-size: 56px;">[abc</li><li style="font-size: 56px;"><br>]<br></li></ul>',
    });
});

test("should apply font size to a fully selected list item with trailing empty line (3)", async () => {
    pinMarkerWidth(19);
    await testEditor({
        styleContent: pinRootFontSize("14px"),
        contentBefore: "<ul><li>[abc</li><li>abcd<br>]<br></li></ul>",
        stepFunction: setFontSize("56px"),
        contentAfter:
            '<ul style="padding-inline-start: 38px;"><li style="font-size: 56px;">[abc</li><li style="font-size: 56px;">abcd<br>]<br></li></ul>',
    });
});

test("should not apply font size to list item when selection excludes trailing empty line", async () => {
    pinMarkerWidth(19);
    await testEditor({
        styleContent: pinRootFontSize("14px"),
        contentBefore: "<ul><li>[abc</li><li>abcd]<br><br></li></ul>",
        stepFunction: setFontSize("56px"),
        contentAfter:
            '<ul style="padding-inline-start: 38px;"><li style="font-size: 56px;">[abc</li><li><span style="font-size: 56px;">abcd]</span><br><br></li></ul>',
    });
});

test("list padding doubles the marker width for UL but not for OL", async () => {
    // Same pinned marker, same font size: a UL doubles it, an OL does not.
    // This is the one asymmetry in adjustListPadding's arithmetic, and it was
    // previously only observable through environment-dependent pixel values.
    pinMarkerWidth(25);
    await testEditor({
        styleContent: pinRootFontSize("16px"),
        contentBefore: "<ul><li>[abc]</li></ul>",
        stepFunction: setFontSize("56px"),
        contentAfter:
            '<ul style="padding-inline-start: 50px;"><li style="font-size: 56px;">[abc]</li></ul>',
    });
    pinMarkerWidth(25);
    await testEditor({
        styleContent: pinRootFontSize("16px"),
        contentBefore: "<ol><li>[abc]</li></ol>",
        stepFunction: setFontSize("56px"),
        // 25 * 1 = 25px, which does NOT exceed the 32px default -> no padding.
        contentAfter: '<ol><li style="font-size: 56px;">[abc]</li></ol>',
    });
});

test("list padding is left untouched when the marker fits the default padding", async () => {
    // round(15) * 2 = 30px <= 32px default (2 * 16px root) -> no inline style.
    pinMarkerWidth(15);
    await testEditor({
        styleContent: pinRootFontSize("16px"),
        contentBefore: "<ul><li>[abc]</li></ul>",
        stepFunction: setFontSize("56px"),
        contentAfter: '<ul><li style="font-size: 56px;">[abc]</li></ul>',
    });
});

test("list padding rounds the measured marker width", async () => {
    // Sub-pixel rasterizer output must not leak into the style attribute.
    pinMarkerWidth(19.4);
    await testEditor({
        styleContent: pinRootFontSize("16px"),
        contentBefore: "<ul><li>[abc]</li></ul>",
        stepFunction: setFontSize("56px"),
        contentAfter:
            '<ul style="padding-inline-start: 38px;"><li style="font-size: 56px;">[abc]</li></ul>',
    });
});

test("should apply font-size on fully selected list items with empty text nodes at list boundaries", async () => {
    await testEditor({
        contentBefore:
            '<ul><li><a href="#">abc</a></li><li><a href="#">abc</a></li></ul>',
        contentBeforeEdit:
            '<ul><li>\ufeff<a href="#">\ufeffabc\ufeff</a>\ufeff</li><li>\ufeff<a href="#">\ufeffabc\ufeff</a>\ufeff</li></ul>',
        stepFunction: (editor) => {
            const listItems = editor.editable.querySelectorAll("li");
            // Set selection here because injected \ufeff can be excluded
            // from the DOM range.
            editor.shared.selection.setSelection({
                anchorNode: listItems[0].firstChild,
                anchorOffset: 0,
                focusNode: listItems[1].lastChild,
                focusOffset: nodeSize(listItems[1].lastChild),
            });
            // Empty text node at start of first <li>
            listItems[0].insertBefore(
                document.createTextNode(""),
                listItems[0].firstChild,
            );
            // Empty text node at end of second <li>
            listItems[1].appendChild(document.createTextNode(""));
            setFontSize("32px")(editor);
        },
        contentAfterEdit:
            '<ul><li style="font-size: 32px;">[\ufeff<a href="#">\ufeffabc\ufeff</a>\ufeff</li><li style="font-size: 32px;">\ufeff<a href="#">\ufeffabc\ufeff</a>\ufeff]</li></ul>',
        contentAfter:
            '<ul><li style="font-size: 32px;">[<a href="#">abc</a></li><li style="font-size: 32px;"><a href="#">abc</a>]</li></ul>',
    });
});

test("should replace list item inline font-size with font-size class", async () => {
    await testEditor({
        contentBefore: '<ul><li style="font-size: 18px;">[abc]</li></ul>',
        stepFunction: (editor) =>
            execCommand(editor, "formatFontSizeClassName", { className: "h2-fs" }),
        contentAfter: '<ul><li class="h2-fs">[abc]</li></ul>',
    });
});

test("should apply font-size to completely selected and partially selected list items", async () => {
    await testEditor({
        contentBefore: "<ol><li>[abc</li><li>def</li><li>gh]i</li></ol>",
        stepFunction: setFontSize("18px"),
        contentAfter:
            '<ol><li style="font-size: 18px;">[abc</li><li style="font-size: 18px;">def</li><li><span style="font-size: 18px;">gh]</span>i</li></ol>',
    });
});

test("should apply font-size to completely selected list items and paragraph tag", async () => {
    await testEditor({
        contentBefore: "<ul><li>[abc</li><li>def</li></ul><p>ghi]</p>",
        stepFunction: (editor) =>
            execCommand(editor, "formatFontSizeClassName", { className: "h2-fs" }),
        contentAfter: `<ul><li class="h2-fs">[abc</li><li class="h2-fs">def</li></ul><p><span class="h2-fs">ghi]</span></p>`,
    });
});

test("should carry list item font-size to new list item", async () => {
    await testEditor({
        contentBefore: '<ol><li>abc</li><li style="font-size: 18px;">def[]</li></ol>',
        stepFunction: splitBlock,
        contentAfter:
            '<ol><li>abc</li><li style="font-size: 18px;">def</li><li style="font-size: 18px;">[]<br></li></ol>',
    });
});

test("should carry list item font-size to new list item (2)", async () => {
    await testEditor({
        contentBefore: '<ul><li class="h2-fs">[]abc</li><li>def</li></ul>',
        stepFunction: splitBlock,
        contentAfter: `<ul><li class="h2-fs"><br></li><li class="h2-fs">[]abc</li><li>def</li></ul>`,
    });
});

test("should carry font-size of paragraph to list item", async () => {
    await testEditor({
        contentBefore: '<p><span style="font-size: 18px;">[]abc</span></p>',
        stepFunction: toggleUnorderedList,
        contentAfter: '<ul><li style="font-size: 18px;">[]abc</li></ul>',
    });
});

test("should carry font-size of paragraph to list item (2)", async () => {
    await testEditor({
        contentBefore:
            '<ol><li class="h3-fs">abc</li></ol><p><span class="h2-fs">[]def</span></p><ol><li>ghi</li></ol>',
        stepFunction: toggleOrderedList,
        contentAfter: `<ol><li class="h3-fs">abc</li><li class="h2-fs">[]def</li><li>ghi</li></ol>`,
    });
});

test("should carry font-size of paragraph to list item (3)", async () => {
    await testEditor({
        contentBefore:
            '<ul><li style="font-size: 18px;">abc</li></ul><p>[]def</p><ul><li style="font-size: 18px;">ghi</li></ul>',
        stepFunction: toggleUnorderedList,
        contentAfter:
            '<ul><li style="font-size: 18px;">abc</li><li>[]def</li><li style="font-size: 18px;">ghi</li></ul>',
    });
});

test("should carry font-size of list item to paragraph", async () => {
    await testEditor({
        contentBefore: '<ol><li style="font-size: 18px;">[]abc</li><li>def</li></ol>',
        stepFunction: toggleOrderedList,
        contentAfter:
            '<p><span style="font-size: 18px;">[]abc</span></p><ol><li>def</li></ol>',
    });
});

test("should carry font-size of list item to paragraph (2)", async () => {
    await testEditor({
        contentBefore:
            '<ul><li class="h2-fs">abc</li><li class="h2-fs">[]def</li><li>ghi</li></ul>',
        stepFunction: toggleUnorderedList,
        contentAfter: `<ul><li class="h2-fs">abc</li></ul><p><span class="h2-fs">[]def</span></p><ul><li>ghi</li></ul>`,
    });
});

test("should carry font-size of list item to paragraph (3)", async () => {
    await testEditor({
        contentBefore:
            '<ol><li style="font-size: 18px;">abc</li><li>[]def</li><li>ghi</li></ol>',
        stepFunction: toggleOrderedList,
        contentAfter:
            '<ol><li style="font-size: 18px;">abc</li></ol><p>[]def</p><ol><li>ghi</li></ol>',
    });
});

test("should carry font-size of list item to paragraph (4)", async () => {
    await testEditor({
        contentBefore:
            '<ol><li style="font-size: 18px;">abc<span style="font-size: 32px;">def</span>ghi[]</li></ol>',
        stepFunction: toggleOrderedList,
        contentAfter:
            '<p><span style="font-size: 18px;">abc<span style="font-size: 32px;">def</span>ghi[]</span></p>',
    });
});

test.tags("font-dependent");
test("should keep list item font-size on toggling list twice", async () => {
    await testEditor({
        styleContent: pinFont("14px"),
        contentBefore:
            '<ol><li style="font-size: 18px;">[abc</li><li style="font-size: 32px;">def]</li></ol>',
        stepFunction: (editor) => {
            toggleOrderedList(editor);
            toggleOrderedList(editor);
            // Strip padding-inline-start from the OL — its exact value
            // depends on font rendering and varies across environments.
            editor.editable
                .querySelector("ol")
                ?.style.removeProperty("padding-inline-start");
        },
        contentAfter:
            '<ol><li style="font-size: 18px;">[abc</li><li style="font-size: 32px;">def]</li></ol>',
    });
});

test("should change font-size of a list item", async () => {
    await testEditor({
        contentBefore:
            '<ul><li style="font-size: 18px;">[abc]</li><li style="font-size: 18px;">ghi</li></ul>',
        stepFunction: setFontSize("32px"),
        contentAfter: `<ul><li style="font-size: 32px;">[abc]</li><li style="font-size: 18px;">ghi</li></ul>`,
    });
});

test.tags("font-dependent");
test("should change font-size of a list item (2)", async () => {
    await testEditor({
        styleContent: pinFont("14px"),
        contentBefore:
            '<ol><li style="font-size: 18px;">[abc</li><li style="font-size: 18px;">ghi]</li></ol>',
        stepFunction: setFontSize("32px"),
        contentAfter: `<ol style="padding-inline-start: 34px;"><li style="font-size: 32px;">[abc</li><li style="font-size: 32px;">ghi]</li></ol>`,
    });
});

test("should change font-size of subpart of a list item", async () => {
    await testEditor({
        contentBefore:
            '<ol><li style="font-size: 18px;">a[b]c</li><li style="font-size: 18px;">ghi</li></ol>',
        stepFunction: setFontSize("32px"),
        contentAfter:
            '<ol><li style="font-size: 18px;">a<span style="font-size: 32px;">[b]</span>c</li><li style="font-size: 18px;">ghi</li></ol>',
    });
});

test("should change font-size of subpart of a list item (2)", async () => {
    await testEditor({
        contentBefore:
            '<ol><li style="font-size: 18px;">a[bc</li><li style="font-size: 18px;">gh]i</li></ol>',
        stepFunction: setFontSize("32px"),
        contentAfter:
            '<ol><li style="font-size: 18px;">a<span style="font-size: 32px;">[bc</span></li><li style="font-size: 18px;"><span style="font-size: 32px;">gh]</span>i</li></ol>',
    });
});

test("should pad list based on font-size", async () => {
    const className = "h2-fs";
    await testEditor({
        contentBefore: "<ol><li>[a]</li></ol>",
        stepFunction: (editor) =>
            execCommand(editor, "formatFontSizeClassName", { className }),
        contentAfter: `<ol><li class="${className}">[a]</li></ol>`,
    });
});

test.tags("font-dependent");
test("should pad list based on font-size (2)", async () => {
    await testEditor({
        styleContent: pinFont("14px"),
        contentBefore: `<span style="font-size: 56px">[a]</span>`,
        stepFunction: toggleOrderedList,
        contentAfter: `<ol style="padding-inline-start: 60px;"><li style="font-size: 56px;">[]a</li></ol>`,
    });
});

test.tags("font-dependent");
test("should apply color to a list containing sublist if list contents are fully selected", async () => {
    await testEditor({
        styleContent: pinFont("14px"),
        contentBefore: "<ol><li><p>[abc]</p><ol><li>def</li></ol></li></ol>",
        stepFunction: setFontSize("56px"),
        contentAfter: `<ol style="padding-inline-start: 60px;"><li style="font-size: 56px;"><p>[abc]</p><ol class="o_default_font_size"><li>def</li></ol></li></ol>`,
    });
});

test("should remove font-size from list item", async () => {
    await testEditor({
        styleContent: pinFont("14px"),
        contentBefore: `<ol><li style="font-size: 56px;">[a]</li></ol>`,
        stepFunction: (editor) => execCommand(editor, "removeFormat"),
        contentAfter: `<ol><li>[a]</li></ol>`,
    });
});

test("should remove font-size class from list item", async () => {
    await testEditor({
        styleContent: pinFont("14px"),
        contentBefore: `<ol><li class="h2-fs">[a]</li></ol>`,
        stepFunction: (editor) => execCommand(editor, "removeFormat"),
        contentAfter: `<ol><li>[a]</li></ol>`,
    });
});

test("should remove font-size from list item containing sublist", async () => {
    await testEditor({
        styleContent: pinFont("14px"),
        contentBefore: `<ol><li>a</li><li style="font-size: 56px;"><p>[b]</p><ol class="o_default_font_size"><li>c</li></ol></li></ol>`,
        stepFunction: (editor) => execCommand(editor, "removeFormat"),
        contentAfter: `<ol><li>a</li><li><p>[b]</p><ol><li>c</li></ol></li></ol>`,
    });
});

test("should remove font-size class from list item containing sublist", async () => {
    await testEditor({
        styleContent: pinFont("14px"),
        contentBefore: `<ol><li>a</li><li class="h2-fs"><p>[b]</p><ol class="o_default_font_size"><li>c</li></ol></li></ol>`,
        stepFunction: (editor) => execCommand(editor, "removeFormat"),
        contentAfter: `<ol><li>a</li><li><p>[b]</p><ol><li>c</li></ol></li></ol>`,
    });
});

test("should remove font-size and its classes from partially selected list item (1)", async () => {
    await testEditor({
        styleContent: pinFont("14px"),
        contentBefore: `<ol><li>a</li><li style="font-size: 56px;">b[c]d</li><li>e</li></ol>`,
        stepFunction: (editor) => execCommand(editor, "removeFormat"),
        contentAfter: `<ol style="padding-inline-start: 60px;"><li>a</li><li style="font-size: 56px;">b<span class="o_default_font_size">[c]</span>d</li><li>e</li></ol>`,
    });
});

test("should remove font-size and its classes from partially selected list item (2)", async () => {
    await testEditor({
        styleContent: pinFont("14px"),
        contentBefore: `<ol><li>a</li><li class="h2-fs">b[c]d</li><li>e</li></ol>`,
        stepFunction: (editor) => execCommand(editor, "removeFormat"),
        contentAfter: `<ol><li>a</li><li class="h2-fs">b<span class="o_default_font_size">[c]</span>d</li><li>e</li></ol>`,
    });
});

test("should remove font-size and its classes from partially selected list item (3)", async () => {
    await testEditor({
        styleContent: pinFont("14px"),
        contentBefore: `<ol><li style="font-size: 56px;">a[bc</li><li style="font-size: 56px;">def</li><li style="font-size: 56px;">gh]i</li></ol>`,
        stepFunction: (editor) => execCommand(editor, "removeFormat"),
        contentAfter: `<ol style="padding-inline-start: 60px;"><li style="font-size: 56px;">a<span class="o_default_font_size">[bc</span></li><li>def</li><li style="font-size: 56px;"><span class="o_default_font_size">gh]</span>i</li></ol>`,
    });
});

test("should remove font-size and its classes from partially selected list item (4)", async () => {
    await testEditor({
        styleContent: pinFont("14px"),
        contentBefore: `<ol><li class="h2-fs">a[bc</li><li class="h2-fs">def</li><li class="h2-fs">gh]i</li></ol>`,
        stepFunction: (editor) => execCommand(editor, "removeFormat"),
        contentAfter: `<ol><li class="h2-fs">a<span class="o_default_font_size">[bc</span></li><li>def</li><li class="h2-fs"><span class="o_default_font_size">gh]</span>i</li></ol>`,
    });
});
