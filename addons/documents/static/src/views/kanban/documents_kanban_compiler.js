/** @odoo-module native */
import { KanbanCompiler } from "@web/views/kanban";
import { isTextNode } from "@web/views/view_compiler";
import { createElement } from "@web/core/utils/dom/xml";

export class DocumentsKanbanCompiler extends KanbanCompiler {
    setup() {
        super.setup();
        this.compilers.push({ selector: "[t-name='card']", fn: this.compileCard });
        this.compilers.push({ selector: "div.o_documents_attachment", fn: this.compileDocumentsAttachment });
        this.compilers.push({ selector: "div.o_kanban_image_wrapper", fn: this.compileImageWrapper });
    }

    /**
     * @override
     */
    compileCard() {
        const result = super.compileGenericNode(...arguments);
        const cards = result.childNodes;
        for (const card of cards) {
            if (isTextNode(card)) {
                continue;
            }
            const dummyElement = createElement("a");
            dummyElement.classList.add("o_hidden", "o_documents_dummy_action");
            card.prepend(dummyElement);
            const fileInput = card.querySelector("input.o_kanban_replace_document");
            if (fileInput) {
                fileInput.setAttribute("t-on-change.stop.prevent", `(ev) => __comp__.props.record.onReplaceDocument(ev)`);
                fileInput.setAttribute("t-on-click.stop", `() => {}`);
            }
        }
        return result;
    }

    compileDocumentsAttachment() {
        const elem = super.compileGenericNode(...arguments);
        elem.setAttribute(
            "t-attf-class",
            (elem.getAttribute("t-attf-class") || "")
            + " {{(record.type.raw_value === 'binary' && !record.attachment_id.raw_value && !record.shortcut_document_id.raw_value) ? 'oe_file_request' : ''}}"
            + " {{__comp__.props.record.selected ? 'o_record_selected' : ''}}"
        );
        const content = new DOMParser().parseFromString(
             `
            <t>
                <t t-set="fileUpload" t-value="__comp__.getFileUpload()"/>
                <t t-if="fileUpload">
                    <FileUploadProgressBar fileUpload="fileUpload"/>
                </t>
            </t>
            `,
            "application/xml"
        );
        elem.prepend(...content.documentElement.children);
        return elem;
    }

    compileImageWrapper() {
        const elem = super.compileGenericNode(...arguments);
        elem.setAttribute(
            "t-attf-class",
            (elem.getAttribute("t-attf-class") || "") +
                " {{(hasStoredThumbnail or youtubeVideoToken or __comp__.props.record.isViewable()) ? 'oe_kanban_previewer' : ''}}"
        );
        return elem;
    }
}
