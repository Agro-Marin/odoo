/** @odoo-module native */

import {
    clickOnSave,
    insertSnippet,
    registerWebsitePreviewTour,
} from "@website/js/tours/tour_utils";

registerWebsitePreviewTour(
    "snippet_popup_open_on_top",
    {
        url: "/",
        edition: true,
    },
    () => [
        ...insertSnippet({
            name: "Popup",
            id: "s_popup",
            groupName: "Content",
        }),
        {
            content: "Change content for long text.",
            trigger: ":iframe .s_popup p.lead",
            run: "editor " + " hello world".repeat(300),
        },
        {
            content: "Set delay to 0 second",
            trigger: '[data-action-id="setPopupDelay"] input',
            run: "edit 0",
        },
        ...clickOnSave(),
        {
            content: "Check that the modal is scrolled on top",
            trigger: ":iframe .s_popup .modal.show:contains('hello world')",
            run: async function () {
                const modalEl = this.anchor;
                let activeEl = modalEl.ownerDocument.activeElement;
                if (activeEl.parentElement.closest(".modal") !== modalEl) {
                    await new Promise((resolve) =>
                        modalEl.addEventListener("shown.bs.modal", resolve),
                    );
                }
                if (modalEl.scrollHeight <= modalEl.clientHeight) {
                    console.error("There is no scrollbar on the modal");
                }
                activeEl = modalEl.ownerDocument.activeElement;
                if (activeEl.parentElement.closest(".modal") !== modalEl) {
                    console.error("The focus should be on an element inside the modal");
                }
                if (modalEl.scrollTop !== 0) {
                    console.error("The modal scrollbar is not scrolled at the top");
                }
            },
        },
    ],
);
