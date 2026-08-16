/** @odoo-module native */
import { EventBus, useSubEnv } from "@odoo/owl";
import { x2ManyCommands } from "@web/core/network";
import { createDocumentFragmentFromContent } from "@web/core/utils/dom/html";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form";
FormController.props = {
    ...FormController.props,
    fullComposerBus: { type: EventBus, optional: true },
};

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
        if (this.env.services["mail.store"]) {
            this.mailStore = useService("mail.store");
        }
        useSubEnv({
            chatter: {
                fetchThreadData: true,
                fetchMessages: true,
            },
        });
    },
    /** @param {{resId: number, resModel: string}} nextConfiguration */
    onWillLoadRoot(nextConfiguration) {
        super.onWillLoadRoot(...arguments);
        const isSameThread =
            this.model.root?.resId === nextConfiguration.resId &&
            this.model.root?.resModel === nextConfiguration.resModel;
        if (isSameThread) {
            this.env.chatter.fetchThreadData = true;
        }
        this.env.chatter.fetchMessages = true;
        if (isSameThread) {
            const { resModel, resId } = this.model.root;
            this.env.bus.trigger("MAIL:RELOAD-THREAD", { model: resModel, id: resId });
        }
    },

    /**
     * @param {import("@web/model/relational_model/record").RelationalRecord} record
     * @param {Object} changes
     */
    async onWillSaveRecord(record, changes) {
        if (record.resModel === "mail.compose.message") {
            if (!changes.body) {
                return;
            }
            const doc = createDocumentFragmentFromContent(changes.body);
            const partnerElements = doc.querySelectorAll(
                '[data-oe-model="res.partner"]',
            );
            const partnerIds = Array.from(partnerElements).map((element) =>
                parseInt(element.dataset.oeId),
            );
            if (partnerIds.length) {
                changes.partner_ids ??= [];
                if (
                    changes.partner_ids[0] &&
                    changes.partner_ids[0][0] === x2ManyCommands.SET
                ) {
                    partnerIds.push(...changes.partner_ids[0][2]);
                }
                changes.partner_ids.push(
                    ...partnerIds.map((pid) => x2ManyCommands.link(pid)),
                );
            }
        }
    },
});
