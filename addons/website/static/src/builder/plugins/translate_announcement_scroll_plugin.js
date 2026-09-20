/** @odoo-module native */
import { InputConfirmationDialog } from "@html_builder/snippets/input_confirmation_dialog";
import { Plugin } from "@html_editor/plugin";
import { makeLogger } from "@web/core/debug/debug_logger";
import { _t } from "@web/core/translation";

const log = makeLogger("website.builder.translation.translate_announcement_scroll");

export class TranslateAnnouncementScrollPlugin extends Plugin {
    static id = "translateAnnouncementScroll";
    static dependencies = ["history"];

    /** @type {import("plugins").WebsiteResources} */
    resources = {
        mark_translatable_nodes: this.listenToAnnouncementScrollClick.bind(this),
    };

    listenToAnnouncementScrollClick() {
        const announcementScrollEls = this.document.querySelectorAll(
            ".s_announcement_scroll",
        );
        log.pipeline("listenToAnnouncementScrollClick", () => ({
            count: announcementScrollEls.length,
        }));

        for (const announcementScrollEl of announcementScrollEls) {
            this.addDomListener(announcementScrollEl, "click", () => {
                this.rollbackHistory = this.dependencies.history.makeSavePoint();

                const translatableEl = announcementScrollEl.querySelector(
                    ".s_announcement_scroll_marquee_item:first-child > [data-oe-translation-source-sha]",
                );

                log.lifecycle("translate dialog open");
                this.services.dialog.add(InputConfirmationDialog, {
                    defaultValue: translatableEl.textContent,
                    title: _t("Translate Text"),
                    confirmLabel: _t("Save"),
                    cancelLabel: _t("Apply"),
                    inputLabel: _t("Translation"),
                    confirm: this.updateText.bind(this, translatableEl),
                    cancel: (inputValue) => {
                        this.updateText.apply(this, [translatableEl, inputValue]);
                        return false;
                    },
                    dismiss: this.rollbackHistory,
                });
            });
        }
    }
    /**
     * @param {HTMLElement} translatableEl
     * @param {String} inputValue
     */
    updateText(translatableEl, inputValue) {
        log.logic("updateText", () => ({
            changed: inputValue !== translatableEl.textContent,
        }));
        if (inputValue !== translatableEl.textContent) {
            translatableEl.textContent = inputValue;
            translatableEl.dataset.oeTranslationState = "translated";
            this.dependencies.history.addStep();
        }
    }
}
