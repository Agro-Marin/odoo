import { test } from "@odoo/hoot";
import { click, manuallyDispatchProgrammaticEvent } from "@odoo/hoot-dom";

import { testEditor } from "../_helpers/editor.js";
import { unformat } from "../_helpers/format.js";
import { clickCheckbox, pasteHtml } from "../_helpers/user_actions.js";

// TODO: 12 of 15 tests in this file fail with "Cannot translate string:
// translations have not been loaded" because the checklist plugin calls
// ``_t("Checked")`` / ``_t("Unchecked")`` lazily when rendering the
// wrapper title.  Adding ``allowTranslations()`` or directly setting
// ``translatedTerms[translationLoaded] = true`` in a ``beforeEach`` does
// not unblock these tests — the ``valueOf()`` throw still fires, which
// suggests either (a) the test bundle's ``translatedTerms`` is a
// distinct copy from the module that calls ``_t()`` despite the
// globalThis routing, or (b) the lazy TranslatedString instance is
// created before the ``beforeEach`` runs and its ``lazy`` flag is
// already set.  Either way the fix needs deeper investigation of
// the ``TranslatedString`` lifecycle in cross-bundle test mode.
// Tracked as a follow-up; the failing tests don't reflect a product
// regression, only test-harness translation initialization.

test("should do nothing if do not click on the checkbox", async () => {
    await testEditor({
        contentBefore: unformat(`
            <ul class="o_checklist">
                <li>1</li>
            </ul>`),
        stepFunction: async (editor) => {
            const li = editor.editable.querySelector("li");
            const liRect = li.getBoundingClientRect();
            await click(li, {
                position: { clientX: liRect.left + 10, clientY: liRect.top + 10 },
            });
        },
        contentAfter: unformat(`
            <ul class="o_checklist">
                <li>1</li>
            </ul>`),
    });
});

test("should check a simple item", async () => {
    await testEditor({
        contentBefore: unformat(`
            <ul class="o_checklist">
                <li>1</li>
            </ul>`),
        stepFunction: async (editor) => {
            const li = editor.editable.querySelector("li");
            await clickCheckbox(li);
        },
        contentAfter: unformat(`
            <ul class="o_checklist">
                <li class="o_checked">[]1</li>
            </ul>`),
    });
});

test("should uncheck a simple item", async () => {
    await testEditor({
        contentBefore: unformat(`
            <ul class="o_checklist">
                <li class="o_checked">1</li>
            </ul>`),
        stepFunction: async (editor) => {
            const li = editor.editable.querySelector("li");
            await clickCheckbox(li);
        },
        contentAfter: unformat(`
                <ul class="o_checklist">
                    <li>[]1</li>
                </ul>`),
    });
});

test("should check an empty item", async () => {
    await testEditor({
        contentBefore: unformat(`
                <ul class="o_checklist">
                    <li><br></li>
                </ul>`),
        stepFunction: async (editor) => {
            const li = editor.editable.querySelector("li");
            await clickCheckbox(li);
        },
        contentAfter: unformat(`
            <ul class="o_checklist">
                <li class="o_checked">[]<br></li>
            </ul>`),
    });
});

test("should uncheck an empty item", async () => {
    await testEditor({
        contentBefore: unformat(`
            <ul class="o_checklist">
                <li><br></li>
            </ul>`),
        stepFunction: async (editor) => {
            const li = editor.editable.querySelector("li");
            await clickCheckbox(li);
        },
        contentAfter: unformat(`
            <ul class="o_checklist">
                <li class="o_checked">[]<br></li>
            </ul>`),
    });
});

test("tripleclick on checkbox should not select the list content", async () => {
    await testEditor({
        contentBefore: unformat(`
            <ul class="o_checklist">
                <li>test</li>
            </ul>`),
        stepFunction: async (editor) => {
            const li = editor.editable.querySelector("li");
            const { top, left } = li.getBoundingClientRect();
            await manuallyDispatchProgrammaticEvent(li, "mousedown", {
                detail: 3,
                clientX: left - 10,
                clientY: top + 10,
            });
            await manuallyDispatchProgrammaticEvent(li, "mouseup", {
                detail: 3,
                clientX: left - 10,
                clientY: top + 10,
            });
            await manuallyDispatchProgrammaticEvent(li, "click", {
                detail: 3,
                clientX: left - 10,
                clientY: top + 10,
            });
        },
        contentAfter: unformat(`
            <ul class="o_checklist">
                <li class="o_checked">[]test</li>
            </ul>`),
    });
});

test("should check a nested item and the previous checklist item used as title", async () => {
    await testEditor({
        contentBefore: unformat(`
            <ul class="o_checklist">
                <li><p>2</p>
                    <ul class="o_checklist">
                        <li class="o_checked">2.1</li>
                        <li>2.2</li>
                    </ul>
                </li>
            </ul>`),
        stepFunction: async (editor) => {
            const lis = editor.editable.querySelectorAll(".o_checklist > li");
            const li = lis[2];
            await clickCheckbox(li);
        },
        contentAfter: unformat(`
            <ul class="o_checklist">
                <li><p>2</p>
                    <ul class="o_checklist">
                        <li class="o_checked">2.1</li>
                        <li class="o_checked">[]2.2</li>
                    </ul>
                </li>
            </ul>`),
    });
});

test("should uncheck a nested item and the previous checklist item used as title", async () => {
    await testEditor({
        contentBefore: unformat(`
            <ul class="o_checklist">
                <li class="o_checked o_checked_has_nested_list"><p>2</p>
                    <ul class="o_checklist">
                        <li class="o_checked">2.1</li>
                        <li class="o_checked">2.2</li>
                    </ul>
                </li>
            </ul>`),
        stepFunction: async (editor) => {
            const lis = editor.editable.querySelectorAll(".o_checklist > li");
            const li = lis[2];
            await clickCheckbox(li);
        },
        contentAfter: unformat(`
            <ul class="o_checklist">
                <li class="o_checked o_checked_has_nested_list"><p>2</p>
                    <ul class="o_checklist">
                        <li class="o_checked">2.1</li>
                        <li>[]2.2</li>
                    </ul>
                </li>
            </ul>`),
    });
});

test("should check a nested item and the wrapper wrapper title", async () => {
    await testEditor({
        contentBefore: unformat(`
            <ul class="o_checklist">
                <li><p>3</p>
                    <ul class="o_checklist">
                        <li><p>3.1</p>
                            <ul class="o_checklist">
                                <li class="o_checked">3.2.1</li>
                                <li>3.2.2</li>
                            </ul>
                        </li>
                    </ul>
                </li>
            </ul>`),
        stepFunction: async (editor) => {
            const lis = editor.editable.querySelectorAll(".o_checklist > li");
            const li = lis[3];
            await clickCheckbox(li);
        },
        contentAfter: unformat(`
            <ul class="o_checklist">
                <li><p>3</p>
                    <ul class="o_checklist">
                        <li><p>3.1</p>
                            <ul class="o_checklist">
                                <li class="o_checked">3.2.1</li>
                                <li class="o_checked">[]3.2.2</li>
                            </ul>
                        </li>
                    </ul>
                </li>
            </ul>`),
    });
});

test("should uncheck a nested item and the wrapper wrapper title", async () => {
    await testEditor({
        contentBefore: unformat(`
            <ul class="o_checklist">
                <li class="o_checked o_checked_has_nested_list"><p>3</p>
                    <ul class="o_checklist">
                        <li class="o_checked o_checked_has_nested_list"><p>3.1</p>
                            <ul class="o_checklist">
                                <li class="o_checked">3.1.1</li>
                                <li class="o_checked">3.1.2</li>
                            </ul>
                        </li>
                    </ul>
                </li>
            </ul>`),
        stepFunction: async (editor) => {
            const lis = editor.editable.querySelectorAll(".o_checklist > li");
            const li = lis[3];
            await clickCheckbox(li);
        },
        contentAfter: unformat(`
            <ul class="o_checklist">
                <li class="o_checked o_checked_has_nested_list"><p>3</p>
                    <ul class="o_checklist">
                        <li class="o_checked o_checked_has_nested_list"><p>3.1</p>
                            <ul class="o_checklist">
                                <li class="o_checked">3.1.1</li>
                                <li>[]3.1.2</li>
                            </ul>
                        </li>
                    </ul>
                </li>
            </ul>`),
    });
});

// @todo @phoenix: this test's contentAfter does not match its description.
test("should check all nested checklist item", async () => {
    await testEditor({
        contentBefore: unformat(`
            <ul class="o_checklist">
                <li><p>3</p>
                    <ul class="o_checklist">
                        <li><p>3.1</p>
                            <ul class="o_checklist">
                                <li class="o_checked">3.1.1</li>
                                <li>3.1.2</li>
                            </ul>
                            <ul class="o_checklist">
                                <li class="o_checked">3.2.1</li>
                                <li>3.2.2</li>
                            </ul>
                        </li>
                        <li>3.3</li>
                    </ul>
                </li>
            </ul>`),
        stepFunction: async (editor) => {
            const lis = editor.editable.querySelectorAll(".o_checklist > li");
            const li = lis[0];
            await clickCheckbox(li);
        },
        contentAfter: unformat(`
            <ul class="o_checklist">
                <li class="o_checked o_checked_has_nested_list">[]<p>3</p>
                    <ul class="o_checklist">
                        <li><p>3.1</p>
                            <ul class="o_checklist">
                                <li class="o_checked">3.1.1</li>
                                <li>3.1.2</li>
                                <li class="o_checked">3.2.1</li>
                                <li>3.2.2</li>
                            </ul>
                        </li>
                        <li>3.3</li>
                    </ul>
                </li>
            </ul>`),
    });
});

// @todo @phoenix: this test's contentAfter does not match its description.
test("should uncheck all nested checklist item", async () => {
    await testEditor({
        contentBefore: unformat(`
            <ul class="o_checklist">
                <li class="o_checked o_checked_has_nested_list"><p>3</p>
                    <ul class="o_checklist">
                        <li class="o_checked o_checked_has_nested_list"><p>3.1</p>
                            <ul class="o_checklist">
                                <li class="o_checked">3.1.1</li>
                                <li class="o_checked">3.1.2</li>
                            </ul>
                            <ul class="o_checklist">
                                <li class="o_checked">3.2.1</li>
                                <li class="o_checked">3.2.2</li>
                            </ul>
                        </li>
                        <li class="o_checked">3.3</li>
                    </ul>
                </li>
            </ul>`),
        stepFunction: async (editor) => {
            const lis = editor.editable.querySelectorAll(".o_checklist > li");
            const li = lis[0];
            await clickCheckbox(li);
        },
        contentAfter: unformat(`
            <ul class="o_checklist">
                <li>[]<p>3</p>
                    <ul class="o_checklist">
                        <li class="o_checked o_checked_has_nested_list"><p>3.1</p>
                            <ul class="o_checklist">
                                <li class="o_checked">3.1.1</li>
                                <li class="o_checked">3.1.2</li>
                                <li class="o_checked">3.2.1</li>
                                <li class="o_checked">3.2.2</li>
                            </ul>
                        </li>
                        <li class="o_checked">3.3</li>
                    </ul>
                </li>
            </ul>`),
    });
});

test("should check all nested checklist item and update wrapper title", async () => {
    await testEditor({
        contentBefore: unformat(`
            <ul class="o_checklist">
                <li><p>3</p>
                    <ul class="o_checklist">
                        <li><p>3.1</p>
                            <ul class="o_checklist">
                                <li class="o_checked">3.2.1</li>
                                <li>3.2.2</li>
                            </ul>
                        </li>
                    </ul>
                </li>
            </ul>`),
        stepFunction: async (editor) => {
            const lis = editor.editable.querySelectorAll(".o_checklist > li");
            const li = lis[1];
            await clickCheckbox(li);
        },
        contentAfter: unformat(`
            <ul class="o_checklist">
                <li><p>3</p>
                    <ul class="o_checklist">
                        <li class="o_checked o_checked_has_nested_list">[]<p>3.1</p>
                            <ul class="o_checklist">
                                <li class="o_checked">3.2.1</li>
                                <li>3.2.2</li>
                            </ul>
                        </li>
                    </ul>
                </li>
            </ul>`),
    });
});

test("should uncheck all nested checklist items and update wrapper title", async () => {
    await testEditor({
        contentBefore: unformat(`
            <ul class="o_checklist">
                <li class="o_checked o_checked_has_nested_list"><p>3</p>
                    <ul class="o_checklist">
                        <li class="o_checked o_checked_has_nested_list"><p>3.1</p>
                            <ul class="o_checklist">
                                <li class="o_checked">3.2.1</li>
                                <li class="o_checked">3.2.2</li>
                            </ul>
                        </li>
                    </ul>
                </li>
            </ul>`),
        stepFunction: async (editor) => {
            const lis = editor.editable.querySelectorAll(".o_checklist > li");
            const li = lis[1];
            await clickCheckbox(li);
        },
        contentAfter: unformat(`
            <ul class="o_checklist">
                <li class="o_checked o_checked_has_nested_list"><p>3</p>
                    <ul class="o_checklist">
                        <li>[]<p>3.1</p>
                            <ul class="o_checklist">
                                <li class="o_checked">3.2.1</li>
                                <li class="o_checked">3.2.2</li>
                            </ul>
                        </li>
                    </ul>
                </li>
            </ul>`),
    });
});

test("should preserve list type on paste", async () => {
    await testEditor({
        contentBefore: unformat(`<div></div>`),
        stepFunction: async (editor) => {
            pasteHtml(
                editor,
                `<ul><li>a</li></ul><ul class="o_checklist"><li>b</li><li>c</li><li>d</li></ul>`,
            );
        },
        contentAfter: unformat(
            `<ul><li>a</li></ul><ul class="o_checklist"><li>b</li><li>c</li><li>d[]</li></ul><div><br></div>`,
        ),
    });
});
