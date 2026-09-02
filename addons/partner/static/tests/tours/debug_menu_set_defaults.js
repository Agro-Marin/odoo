import { registry } from "@web/core/registry";
import { stepUtils } from "@web_tour/tour_utils";

const WEBSITE = "https://sherbrooke.example";

registry.category("web_tour.tours").add("debug_menu_set_defaults", {
    url: "/odoo?debug=1",
    steps: () => [
        ...stepUtils.goToAppSteps(
            "partner.partner_menu_root",
            "Open the contacts menu",
        ),
        {
            content: "Create a new contact",
            trigger: ".o_list_button_add",
            run: "click",
        },
        {
            content: "Check that Company is set by default",
            trigger: '.o_field_widget[name="is_company"] input:checked',
        },
        {
            content: "Give the contact a website, so the field holds a value to save",
            trigger: '.o_field_widget[name="website"] input',
            run: `edit ${WEBSITE}`,
        },
        {
            content: "Open the debug menu",
            trigger: ".o_debug_manager button",
            run: "click",
        },
        {
            content: "Click the Set Defaults menu",
            trigger: ".dropdown-item:contains(Set Default Values)",
            run: "click",
        },
        {
            // Setting a <select> to a value it does not offer is a silent
            // no-op: nothing is saved and the failure only surfaces at the
            // last step, blaming the default instead of the dialog. Assert
            // the option first so a breakage names itself here.
            content: "The dialog must actually offer Website",
            trigger: '#formview_default_fields:has(option[value="website"])',
        },
        {
            content: "Choose Website = the address just typed",
            trigger: "#formview_default_fields",
            run: function () {
                const element_field = document.querySelector(
                    "select#formview_default_fields",
                );
                element_field.value = "website";
                element_field.dispatchEvent(new Event("change"));
            },
        },
        {
            content: "Check that there are conditions",
            trigger: "#formview_default_conditions",
            run: "click",
        },
        {
            content: "Save the new default",
            trigger: "footer button:contains(Save default)",
            run: "click",
        },
        {
            content: "Discard the contact creation",
            trigger: "button.o_form_button_cancel",
            run: "click",
        },
        {
            trigger: ".o_action_manager > .o_list_view .o_list_button_add",
            run: "click",
        },
        {
            content: "Check that Website is now filled in by default",
            trigger: `.o_field_widget[name="website"] input:value("${WEBSITE}")`,
        },
        {
            content: "Discard the contact creation",
            trigger: "button.o_form_button_cancel",
            run: "click",
        },
        {
            content: "Wait for discard",
            trigger: ".o_control_panel .o_list_button_add",
        },
    ],
});
