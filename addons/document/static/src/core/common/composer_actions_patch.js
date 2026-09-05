/** @odoo-module native */
import { registerComposerAction } from "@mail/core/common/composer_actions";
import { _t } from "@web/core/translation";

import { SelectAddDocumentCreateDialog } from "@document/views/view_dialogs/select_add_document_create_dialog";

registerComposerAction("add-documents", {
    icon: { template: "document.DocumentsIcon" },
    name: _t("Add from Documents"),
    onSelected: ({ composer, store }) => {
        const thread = composer?.message?.thread || composer.targetThread;
        store.env.services.dialog.add(SelectAddDocumentCreateDialog, {
            resModel: "document.document",
            title: _t("Search: Documents"),
            noCreate: true,
            domain: [
                ["type", "=", "binary"],
                ["shortcut_document_id", "=", false],
            ],
            context: {
                list_view_ref: "document.documents_view_list_add_documents_attachment",
                documents_search_panel_no_trash: true,
                documents_view_secondary: true,
            },
            chatterParams: {
                thread,
                composer,
            },
        });
    },
    sequence: 10,
});
