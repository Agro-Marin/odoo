// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryAllTexts } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import {
    contains,
    mountWithCleanup,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { NameAndSignature } from "@web/components/signature/name_and_signature";

const TINY_PNG =
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+BCQAHBQICJmhD1AAAAABJRU5ErkJggg==";

const getNameAndSignatureButtonNames = () =>
    queryAllTexts(".card-header .col-auto").filter((text) => text.length);

onRpc("/web/sign/get_fonts/", () => ({}));

test("test name_and_signature widget", async () => {
    const props = {
        signature: {
            name: "Don Toliver",
        },
    };
    await mountWithCleanup(NameAndSignature, { props });
    expect(getNameAndSignatureButtonNames()).toEqual(["Auto", "Draw", "Load"]);
    expect(".o_web_sign_auto_select_style").toHaveCount(1);
    expect(".card-header .active").toHaveCount(1);
    expect(".card-header .active").toHaveText("Auto");
    expect(".o_web_sign_name_group input").toHaveCount(1);
    expect(".o_web_sign_name_group input").toHaveValue("Don Toliver");

    await contains(".o_web_sign_draw_button").click();
    expect(getNameAndSignatureButtonNames()).toEqual(["Auto", "Draw", "Load"]);
    expect(".o_web_sign_draw_clear").toHaveCount(1);
    expect(".card-header .active").toHaveCount(1);
    expect(".card-header .active").toHaveText("Draw");

    await contains(".o_web_sign_load_button").click();
    expect(getNameAndSignatureButtonNames()).toEqual(["Auto", "Draw", "Load"]);
    expect(".o_web_sign_load_file").toHaveCount(1);
    expect(".card-header .active").toHaveCount(1);
    expect(".card-header .active").toHaveText("Load");
});

test("test name_and_signature widget without name", async () => {
    await mountWithCleanup(NameAndSignature, { props: { signature: {} } });
    expect(".card-header").toHaveCount(0);
    expect(".o_web_sign_name_group input").toHaveCount(1);
    expect(".o_web_sign_name_group input").toHaveValue("");

    await contains(".o_web_sign_name_group input").fill("plop", { instantly: true });
    expect(getNameAndSignatureButtonNames()).toEqual(["Auto", "Draw", "Load"]);
    expect(".o_web_sign_auto_select_style").toHaveCount(1);
    expect(".card-header .active").toHaveText("Auto");
    expect(".o_web_sign_name_group input").toHaveCount(1);
    expect(".o_web_sign_name_group input").toHaveValue("plop");

    await contains(".o_web_sign_draw_button").click();
    expect(".card-header .active").toHaveCount(1);
    expect(".card-header .active").toHaveText("Draw");
});

test("test name_and_signature widget with noInputName and default name", async function () {
    const props = {
        signature: {
            name: "Don Toliver",
        },
        noInputName: true,
    };
    await mountWithCleanup(NameAndSignature, { props });
    expect(getNameAndSignatureButtonNames()).toEqual(["Auto", "Draw", "Load"]);
    expect(".o_web_sign_auto_select_style").toHaveCount(1);
    expect(".card-header .active").toHaveCount(1);
    expect(".card-header .active").toHaveText("Auto");
});

test("test name_and_signature widget with noInputName and without name", async function () {
    const props = {
        signature: {},
        noInputName: true,
    };
    await mountWithCleanup(NameAndSignature, { props });
    expect(getNameAndSignatureButtonNames()).toEqual(["Draw", "Load"]);
    expect(".o_web_sign_draw_clear").toHaveCount(1);
    expect(".card-header .active").toHaveCount(1);
    expect(".card-header .active").toHaveText("Draw");
});

test("test name_and_signature widget default signature", async function () {
    const props = {
        signature: {
            name: "Brandon Freeman",
            signatureImage:
                "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+BCQAHBQICJmhD1AAAAABJRU5ErkJggg==",
        },
        mode: "draw",
        signatureType: "signature",
        noInputName: true,
    };
    const res = await mountWithCleanup(NameAndSignature, { props });
    expect(res.isSignatureEmpty).toBe(false);
    expect(res.props.signature.isSignatureEmpty).toBe(false);
});

test("test name_and_signature widget update signmode with onSignatureChange prop", async function () {
    let currentSignMode = "";
    const props = {
        signature: { name: "Test Owner" },
        onSignatureChange: function (/** @type {string} */ signMode) {
            if (currentSignMode !== signMode) {
                currentSignMode = signMode;
            }
        },
    };
    await mountWithCleanup(NameAndSignature, { props });
    await contains(".o_web_sign_draw_button").click();
    expect(currentSignMode).toBe("draw");
});

test("test name_and_signature widget with non-breaking spaces", async function () {
    const props = {
        signature: { name: "Non Breaking Spaces" },
    };
    const res = await mountWithCleanup(NameAndSignature, { props });
    expect(res.getCleanedName()).toBe("Non Breaking Spaces");
});

test("test name_and_signature widget with non-breaking spaces and initials mode", async function () {
    const props = {
        signature: { name: "Non Breaking Spaces" },
        signatureType: "initial",
    };
    const res = await mountWithCleanup(NameAndSignature, { props });
    expect(res.getCleanedName()).toBe("N.B.S.");
});

test("printImage serializes concurrent calls with KeepLast (only the last draws)", async () => {
    const res = await mountWithCleanup(NameAndSignature, {
        props: {
            signature: { name: "Test Owner" },
            mode: "draw",
        },
    });

    // The contract is about the canvas, not about promise timing: a superseded
    // call must not paint. It used to be asserted by checking that the loser's
    // promise never settled, which pinned the dangling continuation rather than
    // the behaviour -- a superseded call now returns early, and still does not
    // draw.
    const ctx = res.signaturePad.canvas.getContext("2d");
    patchWithCleanup(ctx, {
        drawImage() {
            expect.step("drawImage");
            return super.drawImage(...arguments);
        },
    });

    const first = res.printImage(TINY_PNG);
    const second = res.printImage(TINY_PNG);

    await Promise.all([first, second]);
    await animationFrame();

    expect.verifySteps(["drawImage"]);
});

test("a signature model handed over without a name is normalised, not crashed on", async () => {
    // A portal template that defines no default_name serialises it as null.
    for (const name of [null, undefined, ""]) {
        /** @type {any} */
        const signature = { name };
        await mountWithCleanup(NameAndSignature, { props: { signature } });
        await animationFrame();
        expect(signature.name).toBe("");
        expect(".o_web_sign_name_input").toHaveValue("");
    }
});
