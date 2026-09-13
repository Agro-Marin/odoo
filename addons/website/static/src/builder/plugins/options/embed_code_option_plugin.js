/** @odoo-module native */
import { BuilderAction } from "@html_builder/core/builder_action";
import { BaseOptionComponent } from "@html_builder/core/utils";
import { BEGIN } from "@html_builder/utils/option_sequence";
import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { cloneContentEls } from "@website/js/utils";

import { EmbedCodeOptionDialog } from "./embed_code_option_dialog.js";

const log = makeLogger("website.builder.plugin.embed_code_option");

export class EmbedCodeOption extends BaseOptionComponent {
    static template = "website.EmbedCodeOption";
    static selector = ".s_embed_code";
}

class EmbedCodeOptionPlugin extends Plugin {
    static id = "embedCodeOption";

    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_options: [withSequence(BEGIN, EmbedCodeOption)],
        so_content_addition_selector: [".s_embed_code"],
        builder_actions: {
            EditCodeAction,
        },
        clean_for_save_handlers: this.cleanForSave.bind(this),
    };

    cleanForSave({ root }) {
        log.pipeline("EmbedCodeOptionPlugin cleanForSave", () => ({
            embeds: root.querySelectorAll(".s_embed_code").length,
        }));
        for (const embedCodeEl of root.querySelectorAll(".s_embed_code")) {
            const embedTemplateEl = embedCodeEl.querySelector(".s_embed_code_saved");
            if (embedTemplateEl) {
                embedCodeEl
                    .querySelector(".s_embed_code_embedded")
                    .replaceChildren(cloneContentEls(embedTemplateEl.content, true));
            }
        }
    }
}

export class EditCodeAction extends BuilderAction {
    static id = "editCode";
    async load({ editingElement }) {
        let newContent;
        log.lifecycle("EditCodeAction open dialog");
        await new Promise((resolve) => {
            this.services.dialog.add(
                EmbedCodeOptionDialog,
                {
                    title: _t("Edit embedded code"),
                    value: this.getTemplateEl(editingElement).innerHTML.trim(),
                    mode: "xml",
                    confirm: (newValue) => {
                        newContent = newValue;
                    },
                },
                { onClose: resolve },
            );
        });
        log.logic("EditCodeAction dialog closed", () => ({
            confirmed: newContent !== undefined,
            length: newContent?.length,
        }));
        return newContent;
    }
    apply({ editingElement, loadResult: content }) {
        if (!content) {
            log.logic("EditCodeAction apply skipped: no content");
            return;
        }
        log.pipeline("EditCodeAction apply", () => ({ length: content.length }));
        this.getTemplateEl(editingElement).content.replaceChildren(
            cloneContentEls(content, true),
        );
        editingElement
            .querySelector(".s_embed_code_embedded")
            .replaceChildren(cloneContentEls(content));
    }
    getTemplateEl(editingElement) {
        return editingElement.querySelector("template.s_embed_code_saved");
    }
}

registry
    .category("website-plugins")
    .add(EmbedCodeOptionPlugin.id, EmbedCodeOptionPlugin);
