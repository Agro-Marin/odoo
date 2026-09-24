// @ts-check
/** @odoo-module native */
import { provideMailContext, useMailContext } from "@mail/utils/common/mail_context";
import { EventBus } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { x2ManyCommands } from "@web/core/network";
import { createDocumentFragmentFromContent } from "@web/core/utils/dom/html";
import { useEventBus, useOptionalService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form";

const log = makeLogger("mail.chatter.form");
FormController.props = {
    ...FormController.props,
    fullComposerBus: { type: EventBus, optional: true },
};

patch(FormController.prototype, {
    setup() {
        super.setup();
        this.bus = useEventBus();
        this.mailStore = useOptionalService("mail.store");
        provideMailContext({
            chatter: {
                fetchThreadData: true,
                fetchMessages: true,
            },
        });
        this.mailContext = useMailContext();
    },
    /** @param {{resId: number, resModel: string}} nextConfiguration */
    onWillLoadRoot(nextConfiguration) {
        super.onWillLoadRoot(...arguments);
        const isSameThread =
            this.model.root?.resId === nextConfiguration.resId &&
            this.model.root?.resModel === nextConfiguration.resModel;
        log.pipeline("onWillLoadRoot", () => ({
            resModel: nextConfiguration.resModel,
            resId: nextConfiguration.resId,
            isSameThread,
        }));
        if (isSameThread) {
            this.mailContext.chatter.fetchThreadData = true;
        }
        this.mailContext.chatter.fetchMessages = true;
        if (isSameThread) {
            const { resModel, resId } = this.model.root;
            this.bus.trigger("MAIL:RELOAD-THREAD", { model: resModel, id: resId });
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
                parseInt(/** @type {HTMLElement} */ (element).dataset.oeId),
            );
            if (partnerIds.length) {
                log.logic("mentioned partners linked on save", () => ({
                    partnerIds,
                }));
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
