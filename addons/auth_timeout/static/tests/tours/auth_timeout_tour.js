import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";

// Resolve the live product-module instance from the loader registry: test
// files load via the import map only (not registerNativeModules), so a
// static import here would bind a second, unshared instance of the module.
const getPasskeyLib = () => odoo.loader.modules.get("@auth_passkey/passkey_lib").passkeyLib;

async function testRPC() {
    const response = await fetch("/web/session/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ params: {} }),
    });
    return response.json();
}

let unpatchPasskeyMethod;
const patchPasskey = {
    trigger: "body",
    run: function () {
        unpatchPasskeyMethod = patch(getPasskeyLib(), {
            async startRegistration() {
                return { id: "foo" };
            },
            async startAuthentication() {
                return { id: "Zm9v" }; // bytes_to_base64url(b"foo") == "Zm9v"
            },
        });
    },
};
const unpatchPasskey = {
    content: "Wait for the identity check to complete before restoring the passkey lib",
    // The "Use passkey" click triggers an async submit that awaits an RPC
    // before calling the (patched) startAuthentication. Unpatching on a bare
    // "body" trigger races that chain and can restore the real WebAuthn lib
    // mid-flight; the dialog only closes once the whole chain succeeded, so
    // anchor on its disappearance.
    trigger: "body:not(:has(form.o_check_identity_form))",
    run: function () {
        unpatchPasskeyMethod();
    },
};

async function retryUntil(predicate, errorMessage = "Condition not met after retries") {
    for (let attempt = 0; attempt < 5; attempt++) {
        const result = await testRPC();
        if (predicate(result)) {
            return;
        }
        await new Promise((r) => setTimeout(r, 1000));
    }
    throw new Error(errorMessage);
}

const assertCheckIdentityForm = {
    content: "Asserts the check identity form is displayed",
    trigger: "form.o_check_identity_form",
};

const assertRPC = {
    content: "Asserts RPC is allowed",
    trigger: "body",
    run: async function () {
        // Multiple attempts because the inactivity is sent through the websocket and there might be a slight delay
        // between the moment the identity check form is displayed and the session is marked as inactive
        // through the websocket.
        await retryUntil((result) => !result?.error, "RPC was prevented unexpectedly");
    },
};

const assertNoRPC = {
    content: "Asserts RPC is prevented",
    trigger: "body",
    run: async function () {
        await retryUntil(
            (result) => result?.error?.data?.name === "odoo.addons.auth_timeout.models.ir_http.CheckIdentityException",
            "RPC was allowed unexpectedly",
        );
    },
};

registry.category("web_tour.tours").add("auth_timeout_tour_lock_timeout_inactivity", {
    url: "/odoo",
    steps: () => [
        {
            trigger: "body",
            run() {
                const oldRpc = rpc._rpc;
                rpc._rpc = function (...args) {
                    return oldRpc(...args).catch((err) => {
                        if (err.data?.name === "odoo.addons.auth_timeout.models.ir_http.CheckIdentityException") {
                            return new Promise(() => {});
                        } else {
                            throw err;
                        }
                    });
                }
            },
        },
        // Check identity using a password
        assertCheckIdentityForm,
        assertNoRPC,
        {
            content: "Switch to password authentication",
            trigger: 'a[data-auth-method="password"]',
            run: "click",
        },
        {
            content: "Enter the password",
            trigger: "form#password input",
            run: "edit foobarbaz",
        },
        {
            content: "Confirm",
            trigger: "form#password button",
            run: "click",
        },
        assertRPC,

        // Check identity using a TOTP by app
        assertCheckIdentityForm,
        assertNoRPC,
        {
            content: "Switch to TOTP authentication",
            trigger: 'a[data-auth-method="totp"]',
            run: "click",
        },
        {
            content: "Enter the TOTP from authenticator app",
            trigger: "form#totp input",
            run: "edit 111111",
        },
        {
            content: "Confirm",
            trigger: "form#totp button",
            run: "click",
        },
        assertRPC,

        // Check identity using a passkey
        assertCheckIdentityForm,
        assertNoRPC,
        patchPasskey,
        {
            content: "Click Use passkey",
            trigger: "form#webauthn button",
            run: "click",
        },
        unpatchPasskey,
        assertRPC,
    ],
});

registry.category("web_tour.tours").add("auth_timeout_tour_lock_timeout_inactivity_2fa", {
    url: "/odoo",
    steps: () => [
        // Check identity using a passkey, which is 2FA by itself, and check an RPC call works
        assertCheckIdentityForm,
        assertNoRPC,
        patchPasskey,
        {
            content: "Click Use passkey",
            trigger: "form#webauthn button",
            run: "click",
        },
        unpatchPasskey,
        assertRPC,

        // Check identity using a password + TOTP for 2FA
        assertCheckIdentityForm,
        assertNoRPC,
        {
            content: "Switch to password authentication",
            trigger: 'a[data-auth-method="password"]',
            run: "click",
        },
        {
            content: "Fill the password",
            trigger: "form#password input",
            run: "edit foobarbaz",
        },
        {
            content: "Confirm",
            trigger: "form#password button",
            run: "click",
        },
        assertNoRPC,
        assertCheckIdentityForm,
        {
            content: "The default authentication, passkey, should be displayed following entering the password",
            trigger: "form#webauthn button",
        },
        {
            content: "Password should not be suggested as 2FA because it was used as first authentication factor",
            trigger: ':not(a[data-auth-method="password"])',
        },
        {
            content: "Switch to totp authentication",
            trigger: 'a[data-auth-method="totp"]',
            run: "click",
        },
        {
            content: "Fill the TOTP code",
            trigger: "form#totp input",
            run: "edit 111111",
        },
        {
            content: "Confirm",
            trigger: "form#totp button",
            run: "click",
        },
        assertRPC,
    ],
});
