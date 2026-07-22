import { contains } from "@web/../tests/utils";
import { registry } from "@web/core/registry";

/**
 * This tour depends on data created by python test in charge of launching it.
 * It is not intended to work when launched from interface. It is needed to test
 * an action (action manager) which is not possible to test with QUnit.
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
                // Place a COLLAPSED caret first, and only select the word in a
                // later step (below). Both actions go through a real DOM Range
                // because a tour `click`/`dblclick` dispatches *synthetic* mouse
                // events, which browsers do not honour for caret placement or
                // word selection -- the document selection would stay in the
                // chatter composer and the toolbar steps would then silently
                // format the WRONG editor.
                //
                // Splitting caret-then-select is not cosmetic. Moving the
                // selection here closes the chatter composer's toolbar overlay,
                // and selecting a word opens this composer's one. Doing both at
                // once makes the overlay list go [chatterToolbar, dialog] ->
                // [dialog, fullToolbar] in a SINGLE render, and OWL's keyed-list
                // diff answers that shape by re-inserting the surviving dialog
                // node (its "node moved left" branch) instead of just dropping
                // the head. Re-inserting the dialog's subtree blurs whatever is
                // focused inside it, so the selection we just made is wiped and
                // the toolbar anchors to an empty range. Closing the old overlay
                // first makes the second patch a pure append, which OWL handles
                // without touching the dialog.
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
