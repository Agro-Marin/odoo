// @ts-check

import { describe, destroy, expect, test } from "@odoo/hoot";
import { press } from "@odoo/hoot-dom";
import { animationFrame, Deferred, tick } from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import {
    contains,
    getService,
    makeDialogMockEnv,
    mountWithCleanup,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { AlertDialog, ConfirmationDialog } from "@web/ui/dialog/confirmation_dialog";
import { MainComponentsContainer } from "@web/ui/main_components_container";

describe.current.tags("desktop");

test("check content confirmation dialog", async () => {
    const env = await makeDialogMockEnv();
    await mountWithCleanup(ConfirmationDialog, {
        env,
        props: {
            body: "Some content",
            title: "Confirmation",
            close: () => {},
            confirm: () => {},
            cancel: () => {},
        },
    });
    expect(".modal-header").toHaveText("Confirmation");
    expect(".modal-body").toHaveText("Some content");
});

test("Without dismiss callback: pressing escape to close the dialog", async () => {
    const close = () => expect.step("Close action");
    const env = await makeDialogMockEnv({ dialogData: { close } });
    await mountWithCleanup(ConfirmationDialog, {
        env,
        props: {
            body: "Some content",
            title: "Confirmation",
            close,
            confirm: () => {
                throw new Error("should not be called");
            },
            cancel: () => {
                expect.step("Cancel action");
            },
        },
    });
    expect.verifySteps([]);
    await press("escape");
    await tick();
    expect.verifySteps(["Cancel action", "Close action"]);
});

test("With dismiss callback: pressing escape to close the dialog", async () => {
    const close = () => expect.step("Close action");
    const env = await makeDialogMockEnv({ dialogData: { close } });
    await mountWithCleanup(ConfirmationDialog, {
        env,
        props: {
            body: "Some content",
            title: "Confirmation",
            close,
            confirm: () => {
                throw new Error("should not be called");
            },
            cancel: () => {
                throw new Error("should not be called");
            },
            dismiss: () => {
                expect.step("Dismiss action");
            },
        },
    });
    await press("escape");
    await tick();
    expect.verifySteps(["Dismiss action", "Close action"]);
});

test("Without dismiss callback: clicking on 'X' to close the dialog", async () => {
    const close = () => expect.step("Close action");
    const env = await makeDialogMockEnv({ dialogData: { close } });
    await mountWithCleanup(ConfirmationDialog, {
        env,
        props: {
            body: "Some content",
            title: "Confirmation",
            close,
            confirm: () => {
                throw new Error("should not be called");
            },
            cancel: () => {
                expect.step("Cancel action");
            },
        },
    });
    await contains(".modal-header .btn-close").click();
    expect.verifySteps(["Cancel action", "Close action"]);
});

test("With dismiss callback: clicking on 'X' to close the dialog", async () => {
    const close = () => expect.step("Close action");
    const env = await makeDialogMockEnv({ dialogData: { close } });
    await mountWithCleanup(ConfirmationDialog, {
        env,
        props: {
            body: "Some content",
            title: "Confirmation",
            close,
            confirm: () => {
                throw new Error("should not be called");
            },
            cancel: () => {
                throw new Error("should not be called");
            },
            dismiss: () => {
                expect.step("Dismiss action");
            },
        },
    });
    await contains(".modal-header .btn-close").click();
    expect.verifySteps(["Dismiss action", "Close action"]);
});

test("clicking on 'Ok'", async () => {
    const env = await makeDialogMockEnv();
    await mountWithCleanup(ConfirmationDialog, {
        env,
        props: {
            body: "Some content",
            title: "Confirmation",
            close: () => {
                expect.step("Close action");
            },
            confirm: () => {
                expect.step("Confirm action");
            },
            cancel: () => {
                throw new Error("should not be called");
            },
        },
    });
    expect.verifySteps([]);
    await contains(".modal-footer .btn-primary").click();
    expect.verifySteps(["Confirm action", "Close action"]);
});

test("clicking on 'Cancel'", async () => {
    const env = await makeDialogMockEnv();
    await mountWithCleanup(ConfirmationDialog, {
        env,
        props: {
            body: "Some content",
            title: "Confirmation",
            close: () => {
                expect.step("Close action");
            },
            confirm: () => {
                throw new Error("should not be called");
            },
            cancel: () => {
                expect.step("Cancel action");
            },
        },
    });
    expect.verifySteps([]);
    await contains(".modal-footer .btn-secondary").click();
    expect.verifySteps(["Cancel action", "Close action"]);
});

test("hotkey on 'Ok'", async () => {
    const env = await makeDialogMockEnv();
    await mountWithCleanup(ConfirmationDialog, {
        env,
        props: {
            body: "Some content",
            title: "Confirmation",
            close: () => {
                expect.step("Close action");
            },
            confirm: () => {
                expect.step("Confirm action");
            },
            cancel: () => {
                throw new Error("should not be called");
            },
        },
    });
    expect.verifySteps([]);
    await press("alt+q");
    await tick();
    expect.verifySteps(["Confirm action", "Close action"]);
});

test("hotkey on 'Cancel'", async () => {
    const env = await makeDialogMockEnv();
    await mountWithCleanup(ConfirmationDialog, {
        env,
        props: {
            body: "Some content",
            title: "Confirmation",
            close: () => {
                expect.step("Close action");
            },
            confirm: () => {
                throw new Error("should not be called");
            },
            cancel: () => {
                expect.step("Cancel action");
            },
        },
    });
    expect.verifySteps([]);
    await press("alt+x");
    await tick();
    expect.verifySteps(["Cancel action", "Close action"]);
});

test("can't click twice on 'Ok'", async () => {
    const env = await makeDialogMockEnv();
    await mountWithCleanup(ConfirmationDialog, {
        env,
        props: {
            body: "Some content",
            title: "Confirmation",
            close: () => {},
            confirm: () => {
                expect.step("Confirm action");
            },
            cancel: () => {},
        },
    });
    expect.verifySteps([]);
    expect(".modal-footer .btn-primary").not.toHaveAttribute("disabled");
    expect(".modal-footer .btn-secondary").not.toHaveAttribute("disabled");
    await contains(".modal-footer .btn-primary").click();
    expect(".modal-footer .btn-primary").toHaveAttribute("disabled");
    expect(".modal-footer .btn-secondary").toHaveAttribute("disabled");
    expect.verifySteps(["Confirm action"]);
});

test("can't click twice on 'Cancel'", async () => {
    const env = await makeDialogMockEnv();
    await mountWithCleanup(ConfirmationDialog, {
        env,
        props: {
            body: "Some content",
            title: "Confirmation",
            close: () => {},
            confirm: () => {},
            cancel: () => {
                expect.step("Cancel action");
            },
        },
    });
    expect.verifySteps([]);
    expect(".modal-footer .btn-primary").not.toHaveAttribute("disabled");
    expect(".modal-footer .btn-secondary").not.toHaveAttribute("disabled");
    await contains(".modal-footer .btn-secondary").click();
    expect(".modal-footer .btn-primary").toHaveAttribute("disabled");
    expect(".modal-footer .btn-secondary").toHaveAttribute("disabled");
    expect.verifySteps(["Cancel action"]);
});

test("can't cancel (with escape) after confirm", async () => {
    const def = new Deferred();
    const env = await makeDialogMockEnv();
    await mountWithCleanup(ConfirmationDialog, {
        env,
        props: {
            body: "Some content",
            title: "Confirmation",
            close: () => {
                expect.step("Close action");
            },
            confirm: () => {
                expect.step("Confirm action");
                return def;
            },
            cancel: () => {
                throw new Error("should not cancel");
            },
        },
    });
    await contains(".modal-footer .btn-primary").click();
    expect.verifySteps(["Confirm action"]);
    await press("escape");
    await tick();
    expect.verifySteps([]);
    def.resolve();
    await tick();
    expect.verifySteps(["Close action"]);
});

test("wait for confirm callback before closing", async () => {
    const def = new Deferred();
    const env = await makeDialogMockEnv();
    await mountWithCleanup(ConfirmationDialog, {
        env,
        props: {
            body: "Some content",
            title: "Confirmation",
            close: () => {
                expect.step("Close action");
            },
            confirm: () => {
                expect.step("Confirm action");
                return def;
            },
        },
    });
    await contains(".modal-footer .btn-primary").click();
    expect.verifySteps(["Confirm action"]);
    def.resolve();
    await tick();
    expect.verifySteps(["Close action"]);
});

test("Focus is correctly restored after confirmation", async () => {
    const env = await makeDialogMockEnv();

    class Parent extends Component {
        static template = xml`<div class="my-comp"><input type="text" class="my-input"/></div>`;
        static props = ["*"];
    }

    await mountWithCleanup(Parent, { env });
    await contains(".my-input").focus();
    expect(".my-input").toBeFocused();

    const dialog = await mountWithCleanup(ConfirmationDialog, {
        env,
        props: {
            body: "Some content",
            title: "Confirmation",
            confirm: () => {},
            close: () => {},
        },
    });
    expect(".modal-footer .btn-primary").toBeFocused();
    await contains(".modal-footer .btn-primary").click();
    expect(document.body).toBeFocused();
    destroy(dialog);
    await Promise.resolve();
    expect(".my-input").toBeFocused();
});

test("can't click twice on 'Ok' (AlertDialog)", async () => {
    const env = await makeDialogMockEnv();
    await mountWithCleanup(AlertDialog, {
        env,
        props: {
            body: "Some content",
            title: "Alert",
            close: () => {},
            confirm: () => {
                expect.step("Confirm action");
            },
        },
    });
    expect.verifySteps([]);
    expect(".modal-footer .btn-primary").not.toHaveAttribute("disabled");
    await contains(".modal-footer .btn-primary").click();
    expect(".modal-footer .btn-primary").toHaveAttribute("disabled");
    expect.verifySteps(["Confirm action"]);
});

const openConfirmation = async (/** @type {any[]} */ closeParams) => {
    await mountWithCleanup(MainComponentsContainer);
    getService("dialog").add(
        ConfirmationDialog,
        { body: "Some content", confirm: () => {} },
        { onClose: (/** @type {any} */ params) => closeParams.push(params) },
    );
    await animationFrame();
};

test("dismissing reports { dismiss: true } to the dialog service's onClose", async () => {
    /** @type {any[]} */
    const closeParams = [];
    await openConfirmation(closeParams);

    await press("escape");
    await animationFrame();
    await tick();
    expect(closeParams).toEqual([{ dismiss: true }]);
});

test("confirming reports no close params", async () => {
    /** @type {any[]} */
    const closeParams = [];
    await openConfirmation(closeParams);

    await contains(".modal-footer .btn-primary").click();
    await tick();
    expect(closeParams).toEqual([undefined]);
});

const openConfirmationWith = async (/** @type {any} */ props) => {
    await mountWithCleanup(MainComponentsContainer);
    getService("dialog").add(ConfirmationDialog, {
        body: "Some content",
        confirm: () => {},
        ...props,
    });
    await animationFrame();
    expect(".modal").toHaveCount(1);
};

const refusingCancel = () => {
    expect.step("cancel");
    return false;
};

test("Cancel button: a cancel callback returning false keeps the dialog open", async () => {
    await openConfirmationWith({ cancel: refusingCancel });
    await contains(".modal-footer .btn-secondary").click();
    await tick();
    expect.verifySteps(["cancel"]);
    expect(".modal").toHaveCount(1);
});

test("escape: a cancel callback returning false keeps the dialog open", async () => {
    await openConfirmationWith({ cancel: refusingCancel });
    await press("escape");
    await animationFrame();
    await tick();
    expect.verifySteps(["cancel"]);
    expect(".modal").toHaveCount(1);
});

test("header X: a cancel callback returning false keeps the dialog open", async () => {
    await openConfirmationWith({ cancel: refusingCancel });
    await contains(".modal-header .btn-close").click();
    await tick();
    expect.verifySteps(["cancel"]);
    expect(".modal").toHaveCount(1);
});

test("escape: a dismiss callback returning false outranks cancel", async () => {
    await openConfirmationWith({
        cancel: () => expect.step("cancel"),
        dismiss: () => {
            expect.step("dismiss");
            return false;
        },
    });
    await press("escape");
    await animationFrame();
    await tick();
    expect.verifySteps(["dismiss"]);
    expect(".modal").toHaveCount(1);
});

test("dismissing closes the dialog exactly once", async () => {
    await mountWithCleanup(MainComponentsContainer);
    const overlay = getService("overlay");
    const originalAdd = overlay.add;
    patchWithCleanup(overlay, {
        add(/** @type {[any, any, any?]} */ ...args) {
            const remove = originalAdd.apply(this, args);
            return (/** @type {any} */ ...removeArgs) => {
                expect.step(`close(${JSON.stringify(removeArgs[0])})`);
                return remove(...removeArgs);
            };
        },
    });
    getService("dialog").add(ConfirmationDialog, {
        body: "Some content",
        confirm: () => {},
        cancel: () => {},
    });
    await animationFrame();

    await press("escape");
    await animationFrame();
    await tick();
    expect.verifySteps([`close({"dismiss":true})`]);
});
