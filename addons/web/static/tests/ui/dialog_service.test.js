// @ts-check

import { beforeEach, expect, test } from "@odoo/hoot";
import { click, press, queryAll, queryAllTexts, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import { getService, mountWithCleanup } from "@web/../tests/web_test_helpers";
import { MainComponentsContainer } from "@web/components/main_components_container";
import { useAutofocus } from "@web/core/utils/hooks";
import { Dialog } from "@web/ui/dialog/dialog";
import { usePopover } from "@web/ui/popover/popover_hook";

beforeEach(async () => {
    await mountWithCleanup(MainComponentsContainer);
});

test("Simple rendering with a single dialog", async () => {
    class CustomDialog extends Component {
        static components = { Dialog };
        static template = xml`<Dialog title="'Welcome'">content</Dialog>`;
        static props = ["*"];
    }
    expect(".o_dialog").toHaveCount(0);
    getService("dialog").add(CustomDialog);
    await animationFrame();
    expect(".o_dialog").toHaveCount(1);
    expect("header .modal-title").toHaveText("Welcome");
    await click(".o_dialog button");
    await animationFrame();
    expect(".o_dialog").toHaveCount(0);
});

test("Simple rendering and close a single dialog", async () => {
    class CustomDialog extends Component {
        static components = { Dialog };
        static template = xml`<Dialog title="'Welcome'">content</Dialog>`;
        static props = ["*"];
    }
    expect(".o_dialog").toHaveCount(0);
    const removeDialog = getService("dialog").add(CustomDialog);
    await animationFrame();
    expect(".o_dialog").toHaveCount(1);
    expect("header .modal-title").toHaveText("Welcome");

    removeDialog();
    await animationFrame();
    expect(".o_dialog").toHaveCount(0);

    // Calling close again on an already-closed dialog is a no-op, not an error.
    removeDialog();
    expect(".o_dialog").toHaveCount(0);
});

test("rendering with two dialogs", async () => {
    class CustomDialog extends Component {
        static components = { Dialog };
        static template = xml`<Dialog title="props.title">content</Dialog>`;
        static props = ["*"];
    }
    expect(".o_dialog").toHaveCount(0);
    getService("dialog").add(CustomDialog, { title: "Hello" });
    await animationFrame();
    expect(".o_dialog").toHaveCount(1);
    expect("header .modal-title").toHaveText("Hello");

    getService("dialog").add(CustomDialog, { title: "Sauron" });
    await animationFrame();
    expect(".o_dialog").toHaveCount(2);
    expect(queryAllTexts("header .modal-title")).toEqual(["Hello", "Sauron"]);
    await click(".o_dialog button");
    await animationFrame();
    expect(".o_dialog").toHaveCount(1);
    expect("header .modal-title").toHaveText("Sauron");
});

test("multiple dialogs can become the UI active element", async () => {
    class CustomDialog extends Component {
        static components = { Dialog };
        static template = xml`<Dialog title="props.title">content</Dialog>`;
        static props = ["*"];
    }
    getService("dialog").add(CustomDialog, { title: "Hello" });
    await animationFrame();
    expect(queryOne(".o_dialog:not(.o_inactive_modal) .modal")).toBe(
        /** @type {any} */ (getService("ui").activeElement),
    );

    getService("dialog").add(CustomDialog, { title: "Sauron" });
    await animationFrame();
    expect(queryOne(".o_dialog:not(.o_inactive_modal) .modal")).toBe(
        /** @type {any} */ (getService("ui").activeElement),
    );

    getService("dialog").add(CustomDialog, { title: "Rafiki" });
    await animationFrame();
    expect(queryOne(".o_dialog:not(.o_inactive_modal) .modal")).toBe(
        /** @type {any} */ (getService("ui").activeElement),
    );
});

// Desktop-only: ``Dialog`` sets ``bodyTabIndex="0"`` on touch (dialog.js), making
// ``<main.modal-body>`` the first tabbable element instead of ``.btn.test``; and
// ``useAutofocus`` skips focus on touch to avoid popping the keyboard, so
// ``.o_popover input`` isn't auto-focused. Both are correct mobile behavior —
// these focus assertions only hold on desktop.
test.tags("desktop");
test("a popover with an autofocus child can become the UI active element", async () => {
    class TestPopover extends Component {
        static template = xml`<input type="text" t-ref="autofocus" />`;
        static props = ["*"];
        setup() {
            useAutofocus();
        }
    }
    class CustomDialog extends Component {
        static components = { Dialog };
        static template = xml`<Dialog title="props.title">
            <button class="btn test" t-on-click="showPopover">show</button>
        </Dialog>`;
        static props = ["*"];
        setup() {
            this.popover = usePopover(TestPopover);
        }
        showPopover(event) {
            this.popover.open(event.target, {});
        }
    }

    expect(document).toBe(/** @type {any} */ (getService("ui").activeElement));
    expect(document.body).toBeFocused();

    getService("dialog").add(CustomDialog, { title: "Hello" });
    await animationFrame();
    expect(queryOne(".o_dialog:not(.o_inactive_modal) .modal")).toBe(
        /** @type {any} */ (getService("ui").activeElement),
    );
    expect(".btn.test").toBeFocused();

    await click(".btn.test");
    await animationFrame();
    expect(queryOne(".o_popover")).toBe(
        /** @type {any} */ (getService("ui").activeElement),
    );
    expect(".o_popover input").toBeFocused();
});

test("Interactions between multiple dialogs", async () => {
    function activity(modals) {
        const active = [];
        const names = [];
        for (let i = 0; i < modals.length; i++) {
            active[i] = !modals[i].classList.contains("o_inactive_modal");
            names[i] = modals[i].querySelector(".modal-title").textContent;
        }
        return { active, names };
    }

    class CustomDialog extends Component {
        static components = { Dialog };
        static template = xml`<Dialog title="props.title">content</Dialog>`;
        static props = ["*"];
    }

    getService("dialog").add(CustomDialog, { title: "Hello" });
    await animationFrame();
    getService("dialog").add(CustomDialog, { title: "Sauron" });
    await animationFrame();
    getService("dialog").add(CustomDialog, { title: "Rafiki" });
    await animationFrame();

    expect(".o_dialog").toHaveCount(3);
    let res = activity(queryAll(".o_dialog"));
    expect(res.active).toEqual([false, false, true]);
    expect(res.names).toEqual(["Hello", "Sauron", "Rafiki"]);

    await press("Escape", { bubbles: true });
    await animationFrame();

    expect(".o_dialog").toHaveCount(2);
    res = activity(queryAll(".o_dialog"));
    expect(res.active).toEqual([false, true]);
    expect(res.names).toEqual(["Hello", "Sauron"]);

    await click(".o_dialog:not(.o_inactive_modal) button");
    await animationFrame();

    expect(".o_dialog").toHaveCount(1);
    res = activity(queryAll(".o_dialog"));
    expect(res.active).toEqual([true]);
    expect(res.names).toEqual(["Hello"]);

    await click(".o_dialog:not(.o_inactive_modal) button");
    await animationFrame();
    expect(".o_dialog").toHaveCount(0);
});

test("dialog component crashes", async () => {
    expect.errors(1);

    class FailingDialog extends Component {
        static components = { Dialog };
        static template = xml`<Dialog title="'Error'">content</Dialog>`;
        static props = ["*"];
        setup() {
            throw new Error("Some Error");
        }
    }

    getService("dialog").add(FailingDialog);
    await animationFrame();

    expect(".modal .o_error_dialog").toHaveCount(1);
    expect.verifyErrors(["Error: Some Error"]);
});

test("throwing onClose still cleans up stack and body class", async () => {
    class CustomDialog extends Component {
        static components = { Dialog };
        static template = xml`<Dialog title="'Boom'">content</Dialog>`;
        static props = ["*"];
    }
    const close = getService("dialog").add(
        CustomDialog,
        {},
        {
            onClose: () => {
                expect.step("onClose");
                throw new Error("onClose failed");
            },
        },
    );
    await animationFrame();
    expect(".o_dialog").toHaveCount(1);
    expect(document.body).toHaveClass("modal-open");

    // ``close`` returns the (rejected) removal promise; swallow the error so the
    // test asserts the bookkeeping ran despite the throwing onClose.
    await close().catch((error) => expect.step(error.message));
    await animationFrame();

    // Even though onClose threw, the dialog left the stack and the body scroll
    // lock was released (no dialog stuck with ``modal-open`` on <body>).
    expect(".o_dialog").toHaveCount(0);
    expect(document.body).not.toHaveClass("modal-open");
    expect.verifySteps(["onClose", "onClose failed"]);
});

test("two dialogs, close the first one, closeAll", async () => {
    class CustomDialog extends Component {
        static components = { Dialog };
        static template = xml`<Dialog title="props.title">content</Dialog>`;
        static props = ["*"];
    }
    expect(".o_dialog").toHaveCount(0);
    const close = getService("dialog").add(CustomDialog, { title: "Hello" });
    await animationFrame();
    expect(".o_dialog").toHaveCount(1);
    expect("header .modal-title").toHaveText("Hello");

    getService("dialog").add(CustomDialog, { title: "Sauron" });
    await animationFrame();
    expect(".o_dialog").toHaveCount(2);
    expect(queryAllTexts("header .modal-title")).toEqual(["Hello", "Sauron"]);

    close();
    await animationFrame();
    expect(".o_dialog").toHaveCount(1);
    expect("header .modal-title").toHaveText("Sauron");

    getService("dialog").closeAll();
    await animationFrame();
    expect(".o_dialog").toHaveCount(0);
});

test("two dialogs, close the first one twice, then closeAll", async () => {
    class CustomDialog extends Component {
        static components = { Dialog };
        static template = xml`<Dialog title="props.title">content</Dialog>`;
        static props = ["*"];
    }
    expect(".o_dialog").toHaveCount(0);
    getService("dialog").add(
        CustomDialog,
        { title: "Hello" },
        {
            onClose: () => expect.step("close dialog 1"),
        },
    );
    await animationFrame();
    expect(".o_dialog").toHaveCount(1);
    expect("header .modal-title").toHaveText("Hello");
    expect(document.body).toHaveClass("modal-open");

    const close = getService("dialog").add(
        CustomDialog,
        { title: "Sauron" },
        {
            onClose: () => expect.step("close dialog 2"),
        },
    );
    await animationFrame();
    expect(".o_dialog").toHaveCount(2);
    expect(queryAllTexts("header .modal-title")).toEqual(["Hello", "Sauron"]);

    close();
    close();
    await animationFrame();
    expect(".o_dialog").toHaveCount(1);
    expect("header .modal-title").toHaveText("Hello");
    expect(document.body).toHaveClass("modal-open");
    expect.verifySteps(["close dialog 2"]);

    getService("dialog").closeAll();
    await animationFrame();
    expect(".o_dialog").toHaveCount(0);
    expect.verifySteps(["close dialog 1"]);
});
