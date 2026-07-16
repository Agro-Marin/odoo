/** @odoo-module native */
import { EventBus, useSubEnv } from "@odoo/owl";
import { createDocumentFragmentFromContent } from "@web/core/utils/dom/html";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { x2ManyCommands } from "@web/model/relational_model/commands";
import { FormController } from "@web/views/form/form_controller";
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
    onWillLoadRoot(nextConfiguration) {
        super.onWillLoadRoot(...arguments);
        // Both mechanisms are load-bearing despite fetching messages twice on
        // a same-record save: the flags cover renders that follow the reload,
        // while the bus event reaches the already-mounted Thread regardless
        // of render timing. Suppressing either breaks post-save refresh in
        // real flows (e.g. tracking messages posted BY the save) — see the
        // tracking_value suite.
        this.env.chatter.fetchThreadData = true;
        this.env.chatter.fetchMessages = true;
        const isSameThread =
            this.model.root?.resId === nextConfiguration.resId &&
            this.model.root?.resModel === nextConfiguration.resModel;
        if (isSameThread) {
            // not first load
            const { resModel, resId } = this.model.root;
            this.env.bus.trigger("MAIL:RELOAD-THREAD", { model: resModel, id: resId });
        }
    },

    async onWillSaveRecord(record, changes) {
        if (record.resModel === "mail.compose.message") {
            // `changes` is a dirty-field delta: `body`/`partner_ids` are only
            // present when they actually changed. With no body change there are
            // no @mentions to reconcile, so bail before dereferencing either.
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
                // partner_ids may be absent from the delta even when the body
                // (and thus its mentions) changed — seed it before appending.
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
