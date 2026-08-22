/** @odoo-module native */
import { registry } from "@web/core/registry";
import { X2ManyField, x2ManyField } from "@web/fields/relational/x2many";
import { useX2ManyCrud } from "@web/fields/relational/x2many_crud";
import { useOpenX2ManyRecord } from "@web/fields/relational/x2many_dialog";
import { ListRenderer } from "@web/views/list";

const fieldRegistry = registry.category("fields");

export class ChatbotStepsOne2manyRenderer extends ListRenderer {
    setup() {
        super.setup();

        for (const [, properties] of Object.entries(this.fields)) {
            properties.sortable = false;
        }
    }
}

export class ChatbotStepsOne2many extends X2ManyField {
    static components = {
        ...X2ManyField.components,
        ListRenderer: ChatbotStepsOne2manyRenderer,
    };
    setup() {
        super.setup();

        const { saveAndLink, updateRecord } = useX2ManyCrud(
            () => this.list,
            this.isMany2Many,
        );

        const openRecord = useOpenX2ManyRecord({
            resModel: this.list.resModel,
            activeField: this.activeField,
            activeActions: this.activeActions,
            getList: () => this.list,
            saveRecord: async (record) => {
                await saveAndLink(record);
                await this.props.record.save();
            },
            updateRecord: updateRecord,
        });

        this._openRecord = (params) => {
            const activeElement = document.activeElement;
            openRecord({
                ...params,
                onClose: () => {
                    if (activeElement) {
                        activeElement.focus();
                    }
                },
            });
        };
    }
}

export const chatbotStepsOne2many = {
    ...x2ManyField,
    component: ChatbotStepsOne2many,
};

fieldRegistry.add("chatbot_steps_one2many", chatbotStepsOne2many);
