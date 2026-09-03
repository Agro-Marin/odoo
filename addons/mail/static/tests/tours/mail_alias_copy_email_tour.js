import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("mail_alias_copy_email_tour", {
    steps: () => [
        {
            trigger: "[name='alias_name'] input",
            run: "edit jobs",
        },
        {
            trigger: ".o_form_button_save",
            run: "click",
        },
        // the whole address is offered as one copyable value, next to the two
        // fields it is composed of
        {
            trigger: "[name='alias_full_name'] .o_clipboard_button:contains('Copy')",
            run: "click",
        },
        {
            trigger: "[name='alias_full_name'] .o_clipboard_button",
        },
    ],
});
