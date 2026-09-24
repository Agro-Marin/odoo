import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("portal_log_out_a_device", {
    url: "/my/security",
    steps: () => [
        {
            content: "Log out from the other device",
            trigger: ".o_portal_device:contains(Old phone) .o_portal_revoke_device",
            run: "click",
        },
        {
            content: "Logging out a device is an identity-check operation",
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
            content: "This browser is still signed in",
            trigger: "#portal_revoke_all_sessions_popup",
        },
        {
            content: "The other device is gone",
            trigger:
                ".o_portal_devices:not(:has(.o_portal_device:contains(Old phone)))",
        },
    ],
});
