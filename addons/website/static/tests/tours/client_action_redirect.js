/** @odoo-module native */

import { registry } from "@web/core/registry";
import { stepUtils } from "@web_tour/tour_utils";

const testUrl = "/test_client_action_redirect";

const goToBackendSteps = [
    {
        content: "Go to the backend",
        trigger: "body",
        async run() {
            window.location.assign(`/@${testUrl}`);
        },
        expectUnloadPage: true,
    },
    stepUtils.waitIframeIsReady(),
    {
        content: "Check we are in the backend",
        trigger:
            ".o_website_preview :iframe main:has(#test_contact_BE):has(#test_contact_FE)",
    },
];
const checkEditorSteps = [
    {
        content: "Check that the editor is loaded",
        trigger: ":iframe body.editor_enable",
        timeout: 30000,
    },
    {
        content: "exit edit mode",
        trigger: "button[data-action=save]:enabled:contains(save)",
        run: "click",
        timeout: 30000,
    },
    {
        content: "wait for editor to close",
        trigger: ":iframe body:not(.editor_enable)",
    },
];

registry.category("web_tour.tours").add("client_action_redirect", {
    url: testUrl,
    steps: () => [
        {
            content: "Check we are in the frontend",
            trigger: "body:not(:has(.o_website_preview)) #test_contact_FE",
        },
        {
            content: "Click on the link to frontend",
            trigger: "#test_contact_FE",
            run: "click",
            expectUnloadPage: true,
        },
        ...checkEditorSteps,

        ...goToBackendSteps,
        {
            content: "Click on the link to backend",
            trigger: ":iframe #test_contact_BE",
            run: "click",
            expectUnloadPage: true,
        },
        ...checkEditorSteps,

        ...goToBackendSteps,
        {
            content: "Click on the link to backend (2)",
            trigger: ":iframe #test_contact_BE",
            run: "click",
            expectUnloadPage: true,
        },
        ...checkEditorSteps,
    ],
});
