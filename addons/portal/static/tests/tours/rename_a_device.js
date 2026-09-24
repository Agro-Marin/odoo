import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("portal_rename_a_device", {
    url: "/my/security",
    steps: () => [
        {
            content: "Rename the other device",
            trigger: ".o_portal_device:contains(Old phone) .o_portal_rename_device",
            run: "click",
        },
        {
            content: "The dialog starts from the current name",
            trigger: '.modal input[name=name]:value("Old phone")',
            run: "edit Kitchen tablet",
        },
        {
            content: "Save",
            trigger: ".modal-footer button:contains(Save)",
            run: "click",
            expectUnloadPage: true,
        },
        {
            content: "The page shows the new name",
            trigger: ".o_portal_device:contains(Kitchen tablet)",
        },
    ],
});
