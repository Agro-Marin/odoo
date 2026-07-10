// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryAllTexts } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { contains, mountWithCleanup, onRpc } from "@web/../tests/web_test_helpers";
import { NameAndSignature } from "@web/components/signature/name_and_signature";

// Tiny valid 1x1 transparent PNG.
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
        onSignatureChange: function (signMode) {
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
            mode: "draw", // avoid the auto-mode drawing that runs on mount
        },
    });

    let firstResolved = false;
    let secondResolved = false;

    // Fire two draws back-to-back without awaiting the first.
    const p1 = res.printImage(TINY_PNG).then(() => {
        firstResolved = true;
    });
    const p2 = res.printImage(TINY_PNG).then(() => {
        secondResolved = true;
    });

    await p2;
    await animationFrame();

    // The superseded call is abandoned (KeepLast never resolves it), preventing
    // overlapping draws from producing "ghost" renders.
    expect(secondResolved).toBe(true);
    expect(firstResolved).toBe(false);
    void p1;
});
