import { contains } from "@web/../tests/utils";
import { registry } from "@web/core/registry";

/**
 * Depends on data created by the python test in charge of launching it; not
 * intended to work when launched from the interface.
 * @see mail/tests/test_mail_composer.py
 */
registry
    .category("web_tour.tours")
    .add("mail/static/tests/tours/mail_html_composer_test_tour.js", {
        steps: () => [
            {
                content: "Wait for the chatter to be fully loaded",
                trigger: ".o-mail-Chatter",
                async run() {
                    const composerService =
                        odoo.__WOWL_DEBUG__.root.env.services["mail.composer"];
                    composerService.setHtmlComposer();
                    await contains(".o-mail-Message", { count: 1 });
                },
            },
            {
                content: "Click on Send Message",
                trigger: "button:contains(Send message)",
                run: "click",
            },
            {
                content: "Write something in composer",
                trigger: ".o-mail-Composer-html.odoo-editor-editable",
                run: "editor Hello",
            },
            {
                content: "Select the text",
                trigger: ".o-mail-Composer-html.odoo-editor-editable",
                run: "dblclick",
            },
            {
                trigger: ".o-we-toolbar",
            },
            {
                content: "Bold the text",
                trigger: ".o-we-toolbar button[title='Toggle bold']",
                run: "click",
            },
            {
                content: "The bolded text is in the composer",
                trigger:
                    ".o-mail-Composer-html.odoo-editor-editable strong:contains(Hello)",
            },
            {
                content: "Open full composer",
                trigger: "button[title='Open Full Composer']",
                run: "click",
            },
            {
                content: "Check composer keeps the formatted content",
                trigger: ".o_mail_composer_message strong:contains(Hello)",
            },
            {
                // Caret now, selection later, both via real DOM Ranges: synthetic
                // mouse events don't move it, and doing both at once makes OWL
                // re-insert the dialog overlay and blur it.
                content: "Place the caret in the full composer",
                trigger:
                    ".o_mail_composer_message .odoo-editor-editable strong:contains(Hello)",
                async run(actions) {
                    await actions.click();
                    const doc = this.anchor.ownerDocument;
                    const selection = doc.getSelection();
                    const caret = doc.createRange();
                    caret.setStart(this.anchor.firstChild, 0);
                    caret.collapse(true);
                    selection.removeAllRanges();
                    selection.addRange(caret);
                    // `pointerup` is what makes the toolbar plugin re-evaluate.
                    this.anchor.closest(".odoo-editor-editable").dispatchEvent(
                        new MouseEvent("pointerup", {
                            bubbles: true,
                            cancelable: true,
                        }),
                    );
                },
            },
            {
                content: "Wait for the chatter composer's toolbar to close",
                trigger: "body:not(:has(.o-we-toolbar))",
            },
            {
                content: "Select the text in the full composer",
                trigger:
                    ".o_mail_composer_message .odoo-editor-editable strong:contains(Hello)",
                run() {
                    const doc = this.anchor.ownerDocument;
                    const selection = doc.getSelection();
                    const range = doc.createRange();
                    range.selectNodeContents(this.anchor);
                    selection.removeAllRanges();
                    selection.addRange(range);
                    this.anchor.closest(".odoo-editor-editable").dispatchEvent(
                        new MouseEvent("pointerup", {
                            bubbles: true,
                            cancelable: true,
                        }),
                    );
                },
            },
            {
                trigger: ".o-we-toolbar",
            },
            {
                content: "Remove the Bold",
                trigger: ".o-we-toolbar button[title='Toggle bold']",
                run: "click",
            },
            {
                content: "Italicize the text",
                trigger: ".o-we-toolbar button[title='Toggle italic']",
                run: "click",
            },
            {
                content: "The italicized text is in the full composer",
                trigger: ".o_mail_composer_message em:contains(Hello)",
            },
            {
                content: "Close full composer",
                trigger: ".btn-close",
                run: "click",
            },
            {
                content: "Click on Send Message",
                trigger: "button:not(.active):contains(Send message)",
                run: "click",
            },
            {
                content: "The italicized text is in the composer",
                trigger:
                    ".o-mail-Composer-html.odoo-editor-editable em:contains(Hello)",
            },
        ],
    });
