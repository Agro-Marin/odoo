/** @odoo-module native */
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import {
    Many2ManyTagsField,
    many2ManyTagsField,
} from "@web/fields/relational/many2many_tags";

const fieldRegistry = registry.category("fields");

export class ChatbotScriptTriggeringAnswersMany2Many extends Many2ManyTagsField {
    setup() {
        super.setup();

        if (this.props.record.model.root.resId) {
            user.updateContext({
                force_domain_chatbot_script_id: this.props.record.model.root.resId,
            });
        }
    }
}

export const chatbotScriptTriggeringAnswersMany2Many = {
    ...many2ManyTagsField,
    component: ChatbotScriptTriggeringAnswersMany2Many,
};

fieldRegistry.add(
    "chatbot_triggering_answers_widget",
    chatbotScriptTriggeringAnswersMany2Many,
);
