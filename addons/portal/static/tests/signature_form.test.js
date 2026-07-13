import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import { mountWithCleanup, onRpc, patchWithCleanup } from "@web/../tests/web_test_helpers";

import { SignatureForm } from "@portal/signature_form/signature_form";

const SIGN_URL = "/portal/test/sign";

class DummySignature extends Component {
    static template = xml`<div class="o-dummy-signature"/>`;
    static props = ["*"];
}

/**
 * Replace the real NameAndSignature (which pulls the /web/sign/get_fonts route
 * and the signature_pad ESM lib) with a stub. These tests exercise
 * SignatureForm's own state rendering + onClickSubmit, not the signature canvas.
 */
function stubSignatureInput() {
    patchWithCleanup(SignatureForm.components, { NameAndSignature: DummySignature });
}

/**
 * Regression guard for the post-sign success link.
 *
 * The template (portal.SignatureForm) reads ``state.success.redirect_url`` /
 * ``state.success.redirect_message``; ``onClickSubmit`` must publish the server
 * payload under those exact (snake_case) keys. A camelCase regression silently
 * hides the "see your document" link.
 */
test("successful signature renders the server redirect link", async () => {
    stubSignatureInput();
    onRpc(SIGN_URL, () => ({
        message: "Signed!",
        redirect_url: "/my/doc/42",
        redirect_message: "See your document",
    }));

    const component = await mountWithCleanup(SignatureForm, {
        props: { callUrl: SIGN_URL, defaultName: "Alice" },
    });

    await component.onClickSubmit();
    await animationFrame();

    expect(".alert-success a").toHaveCount(1);
    expect(".alert-success a").toHaveAttribute("href", "/my/doc/42");
    expect(".alert-success a").toHaveText("See your document");
});

/**
 * Regression guard for the submit button on RPC failure: the loading state must
 * be reverted (icon restored, control usable) so the user can retry instead of
 * being stuck with a permanently spinning button.
 */
test("a failing signature RPC restores the submit button", async () => {
    stubSignatureInput();
    onRpc(SIGN_URL, () => {
        throw new Error("boom");
    });

    const component = await mountWithCleanup(SignatureForm, {
        props: { callUrl: SIGN_URL, defaultName: "Alice" },
    });

    let rejected = false;
    try {
        await component.onClickSubmit();
    } catch {
        rejected = true;
    }
    await animationFrame();

    expect(rejected).toBe(true);
    // Button still present, its icon restored (removed for the loading state).
    expect(".o_portal_sign_submit").toHaveCount(1);
    expect(".o_portal_sign_submit i.fa-check").toHaveCount(1);
});
