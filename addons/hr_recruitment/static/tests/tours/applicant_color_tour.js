import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("hr_recruitment_applicant_color_tour", {
    url: "/odoo/action-hr_recruitment.crm_case_categ0_act_job",
    steps: () => [
        {
            content: "Switch to the kanban of applications",
            trigger: ".o_switch_view.o_kanban",
            run: "click",
        },
        {
            content: "Open the menu of the application card",
            trigger: ".o_kanban_record:contains(Colourless Candidate)",
            run: "hover && click .o_kanban_record:contains(Colourless Candidate) .o_dropdown_kanban .btn.o-no-caret",
        },
        {
            content: "Pick a colour for the application",
            trigger: ".o_kanban_colorpicker button.o_colorlist_item_color_4",
            run: "click",
        },
        {
            content: "The colour is stored, so the card comes back highlighted",
            trigger: ".o_kanban_record:contains(Colourless Candidate)",
        },
    ],
});
