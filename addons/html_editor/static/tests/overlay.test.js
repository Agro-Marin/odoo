import { getScrollContainer } from "@html_editor/core/overlay";
import { Plugin } from "@html_editor/plugin";
import { MAIN_PLUGINS } from "@html_editor/plugin_sets";
import { parseHTML } from "@html_editor/utils/html";
import { Wysiwyg } from "@html_editor/wysiwyg";
import { beforeEach, describe, expect, getFixture, test } from "@odoo/hoot";
import { click, hover, queryOne, waitFor, waitForNone } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, onMounted, onWillUnmount, xml } from "@odoo/owl";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { closestScrollableY } from "@web/core/utils/dom/scrolling";
import { useService } from "@web/core/utils/hooks";

import { setupEditor } from "./_helpers/editor.js";
import { unformat } from "./_helpers/format.js";
import { setSelection } from "./_helpers/selection.js";
import { insertText } from "./_helpers/user_actions.js";

class Test extends models.Model {
    name = fields.Char();
    txt = fields.Html();
    _records = [
        { id: 1, name: "Test", txt: "<p>text</p>".repeat(50) },
        {
            id: 2,
            name: "Test",
            txt: unformat(`
                <table><tbody>
                    <tr>
                        <td><p>cell 0</p></td>
                        <td><p>cell 1</p></td>
                    </tr>
                </tbody></table>
                ${"<p>text</p>".repeat(50)}`),
        },
        { id: 3, name: "Test", txt: "<p>text</p>" },
    ];
}

defineModels([Test]);

test.tags("desktop");
test("Toolbar should not overflow scroll container", async () => {
    const top = (elementOrRange) => elementOrRange.getBoundingClientRect().top;
    const bottom = (elementOrRange) => elementOrRange.getBoundingClientRect().bottom;

    await mountView({
        type: "form",
        resId: 1,
        resModel: "test",
        arch: `
            <form>
                <field name="name"/>
                <field name="txt" widget="html"/>
            </form>`,
    });

    const scrollableElement = queryOne(".o_content");
    const editable = queryOne(".odoo-editor-editable");

    const fifthParagraph = editable.children[5];
    setSelection({
        anchorNode: fifthParagraph,
        anchorOffset: 0,
        focusNode: fifthParagraph,
        focusOffset: 1,
    });
    const range = document.getSelection().getRangeAt(0);

    const toolbar = await waitFor(".o-we-toolbar");

    expect(bottom(toolbar)).toBeLessThan(top(range));

    let scrollStep = top(toolbar) - top(scrollableElement);
    scrollableElement.scrollTop += scrollStep;
    await animationFrame();

    expect(top(toolbar)).toBeGreaterThan(bottom(range));

    expect(top(toolbar)).toBeGreaterThan(top(scrollableElement));

    scrollStep = top(toolbar) - top(scrollableElement);
    scrollableElement.scrollTop += scrollStep;
    await animationFrame();

    expect(toolbar).not.toBeVisible();

    scrollableElement.scrollTop -= scrollStep;
    await animationFrame();

    expect(toolbar).toBeVisible();
});

test.tags("desktop");
test("Toolbar should be visible after scroll bar is added", async () => {
    await mountView({
        type: "form",
        resId: 3,
        resModel: "test",
        arch: `
            <form>
                <field name="name"/>
                <field name="txt" widget="html" options="{'height': 300}"/>
            </form>`,
    });

    const p = queryOne(".odoo-editor-editable p");

    const morePs = parseHTML(document, "<p>more text</p>".repeat(20));
    p.after(...morePs.childNodes);

    setSelection({ anchorNode: p, anchorOffset: 0, focusNode: p, focusOffset: 1 });

    const toolbar = await waitFor(".o-we-toolbar");
    expect(toolbar).toBeVisible();
});

test.tags("desktop");
test("Toolbar should not overflow scroll container at the bottom", async () => {
    await mountView({
        type: "form",
        resId: 1,
        resModel: "test",
        arch: `
            <form>
                <field name="name"/>
                <field name="txt" widget="html" options="{'height': 300}"/>
            </form>`,
    });
    const lastP = queryOne(".odoo-editor-editable p:last-child");
    lastP.scrollIntoView();

    setSelection({
        anchorNode: lastP,
        anchorOffset: 0,
        focusNode: lastP,
        focusOffset: 1,
    });

    const toolbar = await waitFor(".o-we-toolbar");
    expect(toolbar).toBeVisible();

    const scrollableElement = closestScrollableY(lastP);
    scrollableElement.scrollTop -= 100;

    await waitFor(".o-we-toolbar:not(:visible)");
    expect(toolbar).not.toBeVisible();
});

test.tags("desktop");
test("Toolbar visibility should be updated when editable is resized", async () => {
    await mountView({
        type: "form",
        resId: 1,
        resModel: "test",
        arch: `
            <form>
                <field name="name"/>
                <field name="txt" widget="html" options="{'height': 300}"/>
            </form>`,
    });

    const lastP = queryOne(".odoo-editor-editable p:last-child");
    lastP.scrollIntoView();

    setSelection({
        anchorNode: lastP,
        anchorOffset: 0,
        focusNode: lastP,
        focusOffset: 1,
    });

    const toolbar = await waitFor(".o-we-toolbar");
    expect(toolbar).toBeVisible();

    const editable = queryOne(".odoo-editor-editable");
    editable.style.height = "150px";

    await waitFor(".o-we-toolbar:not(:visible)");
    expect(toolbar).not.toBeVisible();
});

describe("powerbox", () => {
    let editor;
    beforeEach(() =>
        patchWithCleanup(Wysiwyg.prototype, {
            setup() {
                super.setup();
                editor = this.editor;
            },
        }),
    );

    test.tags("desktop");
    test("Powerbox should be visible in a editable with small height", async () => {
        await mountView({
            type: "form",
            resId: 3,
            resModel: "test",
            arch: `
            <form>
                <field name="name"/>
                <field name="txt" widget="html" options="{'height': 100}"/>
            </form>`,
        });

        setSelection({
            anchorNode: queryOne(".odoo-editor-editable p"),
            anchorOffset: 1,
        });
        insertText(editor, "/");

        const powerbox = await waitFor(".o-we-powerbox");
        expect(powerbox).toBeVisible();
    });

    test.tags("desktop");
    test("Powerbox should be visible in a editable with small height (2)", async () => {
        await mountView({
            type: "form",
            resId: 1,
            resModel: "test",
            arch: `
            <form>
                <field name="name"/>
                <field name="txt" widget="html" options="{'height': 100}"/>
            </form>`,
        });

        const thirdP = queryOne(".odoo-editor-editable p:nth-child(3)");
        setSelection({ anchorNode: thirdP, anchorOffset: 1 });
        insertText(editor, "/");

        const powerbox = await waitFor(".o-we-powerbox");
        expect(powerbox).toBeVisible();
    });
});

test.tags("desktop");
test("Table column control should always be displayed on top of the table", async () => {
    const top = (el) => el.getBoundingClientRect().top;
    const bottom = (el) => el.getBoundingClientRect().bottom;

    await mountView({
        type: "form",
        resId: 2,
        resModel: "test",
        arch: `
            <form>
                <field name="name"/>
                <field name="txt" widget="html"/>
            </form>`,
    });

    const scrollableElement = queryOne(".o_content");
    const table = queryOne(".odoo-editor-editable table");
    await hover(".odoo-editor-editable td");
    let columnControl = await waitFor(".o-we-table-menu[data-type='column']");

    expect(bottom(columnControl)).toBe(top(table));

    const distanceToTop = top(table) - top(scrollableElement);
    scrollableElement.scrollTop += distanceToTop;
    await animationFrame();

    await hover(".odoo-editor-editable td");
    columnControl = await waitFor(".o-we-table-menu[data-type='column']");

    expect(bottom(columnControl)).toBe(top(table));
});

test.tags("desktop");
test("Table menu should close on scroll", async () => {
    await mountView({
        type: "form",
        resId: 2,
        resModel: "test",
        arch: `
            <form>
                <field name="name"/>
                <field name="txt" widget="html"/>
            </form>`,
    });

    const scrollableElement = queryOne(".o_content");

    await hover(".odoo-editor-editable td");
    const columnControl = await waitFor(".o-we-table-menu[data-type='column']");
    await click(columnControl);
    await animationFrame();

    expect(".o-dropdown--menu").toBeVisible();

    scrollableElement.scrollTop += 10;
    await waitForNone(".o-dropdown--menu");

    expect(".o-dropdown--menu").not.toHaveCount();
});

test.tags("desktop");
test("Table menu should only show on contenteditable true tables", async () => {
    await mountView({
        type: "form",
        resId: 2,
        resModel: "test",
        arch: `
            <form>
                <field name="name"/>
                <field name="txt" widget="html"/>
            </form>`,
    });

    await hover(".odoo-editor-editable td");
    await waitFor(".o-we-table-menu[data-type='column']");
    expect(".o-we-table-menu[data-type='column']").toBeVisible();

    await hover(".o_control_panel");
    queryOne("table").setAttribute("contenteditable", "false");

    await hover(".odoo-editor-editable td");
    await waitForNone(".o-we-table-menu[data-type='column']");
    expect(".o-we-table-menu[data-type='column']").not.toHaveCount();
});

test("Toolbar should keep stable while extending down the selection", async () => {
    const top = (el) => el.getBoundingClientRect().top;
    const left = (el) => el.getBoundingClientRect().left;

    await mountView({
        type: "form",
        resId: 1,
        resModel: "test",
        arch: `
            <form>
                <field name="name"/>
                <field name="txt" widget="html"/>
            </form>`,
    });

    const editable = queryOne(".odoo-editor-editable");

    const fifthParagraph = editable.children[5];
    const textNode = fifthParagraph.firstChild;
    setSelection({
        anchorNode: textNode,
        anchorOffset: 0,
        focusNode: textNode,
        focusOffset: textNode.length,
    });
    const toolbar = await waitFor(".o-we-toolbar");
    const referenceTop = top(toolbar);
    const referenceLeft = left(toolbar);

    const extendSelection = (focusNode, focusOffset) => {
        setSelection({ anchorNode: textNode, anchorOffset: 0, focusNode, focusOffset });
    };

    const sixthParagraph = fifthParagraph.nextElementSibling;
    extendSelection(sixthParagraph, 0);
    await animationFrame();

    expect(top(toolbar)).toBe(referenceTop);
    expect(left(toolbar)).toBe(referenceLeft);

    const textNodeSixthParagraph = sixthParagraph.firstChild;
    extendSelection(textNodeSixthParagraph, textNodeSixthParagraph.length);
    await animationFrame();

    expect(top(toolbar)).toBe(referenceTop);
    expect(left(toolbar)).toBe(referenceLeft);
});

test("overlay don't close when click on child overlay", async () => {
    class MySubOverlay extends Component {
        static template = xml`<button class="my-suboverlay">Overlay</button>`;
        static props = {};
    }
    class MyOverlay extends Component {
        static template = xml`<div class="my-overlay">Overlay</div>`;
        static props = {};

        setup() {
            const overlayService = useService("overlay");
            let remove;
            onMounted(() => {
                remove = overlayService.add(MySubOverlay, {});
            });
            onWillUnmount(() => remove?.());
        }
    }

    class MyPlugin extends Plugin {
        static id = "my.plugin";
        static dependencies = ["overlay"];
        setup() {
            this.overlay = this.dependencies.overlay.createOverlay(MyOverlay, {});
            this.overlay.open({ target: this.editable });
        }
        destroy() {
            this.overlay.close();
        }
    }

    const { editor } = await setupEditor("<div>edit</div>", {
        config: { Plugins: [...MAIN_PLUGINS, MyPlugin] },
    });
    await waitFor(".my-overlay");
    await contains(".my-suboverlay").click();
    await animationFrame();
    expect(document.activeElement).toBe(queryOne(".my-suboverlay"));
    expect(".my-overlay").toHaveCount(1);
    editor.destroy();
    await animationFrame();

    await setupEditor("<div>edit</div>", {
        config: { Plugins: [...MAIN_PLUGINS, MyPlugin] },
        props: {
            iframe: true,
        },
    });
    await waitFor(".my-overlay");
    await contains(".my-suboverlay").click();
    await animationFrame();
    expect(document.activeElement).toBe(queryOne(".my-suboverlay"));
    expect(".my-overlay").toHaveCount(1);
});

describe("getScrollContainer", () => {
    const addVisualHints = (root) => {
        const style = document.createElement("style");
        style.textContent = `
            .fixed {
                border: 3px solid blue;
            }
            .target {
                border: 3px solid orange;
            }
            .expected {
                border: 3px solid green;
            }
            div, iframe {
                margin: 10px;
            }
        `;
        root.prepend(style);
    };
    const setContent = (html, root = getFixture()) => {
        root.innerHTML = html;
        addVisualHints(root);
        return {
            target: root.querySelector(".target"),
            expected: root.querySelector(".expected"),
            iframe: root.querySelector(".iframe"),
        };
    };

    describe("single document", () => {
        test("should return null", () => {
            const { target } = setContent(`<div class="target">Target</div>`);
            expect(getScrollContainer(target)).toBe(null);
        });
        test("should return null (2)", () => {
            const { target } = setContent(`
                <div style="height: 100px">
                    <div class="target" style="height: 200px;">Target</div>
                </div>`);
            expect(getScrollContainer(target)).toBe(null);
        });
        test("should return the target itself", () => {
            const { target } = setContent(`
                <div class="target" style="height: 100px; overflow-y: auto;">
                    <div style="height: 200px;">Content</div>
                </div>`);
            expect(getScrollContainer(target)).toBe(target);
        });
        test("should return target's parent", () => {
            const { target, expected } = setContent(`
                <div class="expected" style="height: 100px; overflow-y: auto;">
                    <div class="target" style="height: 200px;">Target</div>
                </div>`);
            expect(getScrollContainer(target)).toBe(expected);
        });
        test("should return closest scrollable ancestor", () => {
            const { target, expected } = setContent(`
                <div style="height: 200px; overflow-y: auto;">
                    <div class="expected" style="height: 300px; overflow-y: auto;">
                        <div class="target" style="height: 400px;">Target</div>
                    </div>
                </div>`);
            expect(getScrollContainer(target)).toBe(expected);
        });
        test("should return closest scrollable ancestor (2)", () => {
            const { target, expected } = setContent(`
                <div class="expected" style="height: 300px; overflow-y: auto;">
                    <div style="height: 500px; overflow-y: auto;">
                        <div class="target" style="height: 400px;">Target</div>
                    </div>
                </div>`);
            expect(getScrollContainer(target)).toBe(expected);
        });
    });

    describe("with iframe", () => {
        test("should return closest scrollable ancestor inside the iframe", () => {
            const { iframe } = setContent(
                `<iframe class="iframe" style="height: 500px"></iframe>`,
            );
            const { target, expected } = setContent(
                `<div class="expected" style="height: 300px; overflow-y: auto;">
                    <div class="target" style="height: 400px;">Target</div>
                </div>`,
                iframe.contentDocument.body,
            );
            expect(getScrollContainer(target)).toBe(expected);
        });
        test("should return the iframe's document element", () => {
            const { iframe } = setContent(`
                <iframe class="iframe" style="height: 500px"></iframe>`);
            const { target } = setContent(
                `<div class="target" style="height: 600px;">Target</div>`,
                iframe.contentDocument.body,
            );
            const documentElement = iframe.contentDocument.documentElement;
            documentElement.classList.add("expected");
            expect(getScrollContainer(target)).toBe(documentElement);
        });
        test("should return scrollable element in the enclosing document", () => {
            const { iframe, expected } = setContent(`
                <div class="expected" style="height: 300px; overflow-y: auto;">
                    <iframe class="iframe" style="height: 500px"></iframe>
                </div>`);
            const { target } = setContent(
                `<div class="target" style="height: 400px;">Target</div>`,
                iframe.contentDocument.body,
            );
            expect(getScrollContainer(target)).toBe(expected);
        });
    });

    describe("with fixed elements", () => {
        test("should return scrollable element inside fixed container", () => {
            const { target, expected } = setContent(`
                <div class="fixed" style="position: fixed, height: 600px">
                    <div class="expected" style="height: 300px; overflow-y: auto;">
                        <div class="target" style="height: 400px;">Target</div>
                    </div>
                </div>`);
            expect(getScrollContainer(target)).toBe(expected);
        });
        test("should not consider scrollable ancestor of a fixed element as the scroll container", () => {
            const { target } = setContent(`
                <div style="height: 500px; overflow-y: auto">
                    <div style="height: 700px">
                        <div class="fixed" style="position: fixed">
                            <div class="target" style="height: 400px;">Target</div>
                        </div>
                    </div>
                </div>`);
            expect(getScrollContainer(target)).toBe(null);
        });
        test("should return scrollable element in enclosing document of a fixed element", () => {
            const { iframe, expected } = setContent(`
                <div class="expected" style="height: 300px; overflow-y: auto;">
                    <iframe class="iframe" style="height: 600px"></iframe>
                </div>`);
            const { target } = setContent(
                `<div style="height: 500px; overflow-y: auto">
                    <div style="height: 700px">
                        <div class="fixed" style="position: fixed">
                            <div class="target" style="height: 300px;">Target</div>
                        </div>
                    </div>
                </div>`,
                iframe.contentDocument.body,
            );
            expect(getScrollContainer(target)).toBe(expected);
        });
        test("should return scrollable element in enclosing document of a fixed element (2)", () => {
            const { iframe, expected } = setContent(`
                <div class="expected" style="height: 300px; overflow-y: auto;">
                    <iframe class="iframe" style="height: 600px"></iframe>
                </div>`);
            const { target } = setContent(
                `<div style="height: 700px">
                        <div class="fixed" style="position: fixed">
                            <div class="target" style="height: 300px;">Target</div>
                        </div>
                </div>`,
                iframe.contentDocument.body,
            );
            expect(getScrollContainer(target)).toBe(expected);
        });
        test("should return the fixed container if it is scrollable", () => {
            const { target, expected } = setContent(`
                <div class="expected fixed" style="position: fixed; height: 300px; overflow-y: auto;">
                    <div class="target" style="height: 400px;">Target</div>
                </div>`);
            expect(getScrollContainer(target)).toBe(expected);
        });
    });
});

test("Overlay should be visible when scroll container has negative value for bottom", async () => {
    const bigContent = "<p>line</p>".repeat(100);
    const { el } = await setupEditor(bigContent, { props: { iframe: true } });
    const iframe = el.ownerDocument.defaultView.frameElement;
    iframe.classList.remove("h-100");
    iframe.style.height = "500px";
    el.style.height = "1000px";

    const lastP = el.querySelector("p:last-child");
    lastP.scrollIntoView();

    const scrollContainer = getScrollContainer(el);
    const { bottom } = scrollContainer.getBoundingClientRect();
    expect(bottom).toBeLessThan(0);
    setSelection({
        anchorNode: lastP,
        anchorOffset: 0,
        focusNode: lastP,
        focusOffset: 1,
    });
    await waitFor(".o-we-toolbar");
    expect(".o-we-toolbar").toBeVisible();
});
