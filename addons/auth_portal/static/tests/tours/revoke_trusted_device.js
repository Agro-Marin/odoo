import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("auth_portal_revoke_trusted_device", {
    url: "/my/security",
    steps: () => [
        {
            content: "The trusted device set up by the test is listed",
            trigger: "td:contains(test-device)",
        },
        {
            content: "Revoke it",
            trigger: ".o_totp_portal_revoke_device",
            run: "click",
        },
        {
            content: "Revoking a device is an identity-check operation",
            trigger:
                "form strong:contains(Please enter your password to confirm you own this account)",
        },
        {
            content: "Input password",
            trigger: "form input[name=password]",
            run: "edit portal",
        },
        {
            content: "Confirm",
            trigger: ".modal-footer button:contains(Confirm Password)",
            run: "click",
            expectUnloadPage: true,
        },
        {
            // The whole table is behind t-if="len(user_id.totp_trusted_device_ids)",
            // so revoking the only device takes the row, the table and the
            // "Revoke All" button with it. Asserting on the section that stays
            // proves the page re-rendered rather than merely failing to match.
            content: "The device is gone, and 2FA is still enabled",
            trigger: "button:contains(Disable two-factor authentication)",
        },
        {
            content: "No revoke control is left",
            trigger: "body:not(:has(.o_totp_portal_revoke_device))",
        },
    ],
});
