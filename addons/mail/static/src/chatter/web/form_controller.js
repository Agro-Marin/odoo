/** @odoo-module native */
import { EventBus, useSubEnv } from "@odoo/owl";
import { createDocumentFragmentFromContent } from "@web/core/utils/dom/html";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { x2ManyCommands } from "@web/model/relational_model";
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
    onWillLoadRoot(nextConfiguration) {
        super.onWillLoadRoot(...arguments);
        const isSameThread =
            this.model.root?.resId === nextConfiguration.resId &&
            this.model.root?.resModel === nextConfiguration.resModel;
        // `fetchThreadData` means "same thread, its data may be stale after a
        // save" (@see chatter.js), so it is raised only when the root load
        // keeps the thread. Raised for every load, it was consumed by a render
        // that still held the OUTGOING record and re-fetched that record's
        // activities, attachments, followers and scheduled messages onto a
        // thread the user had just left — one wasted round trip per "Create"
        // click and per record switch, on every chatter form. The switch needs
        // nothing from it: `2b452acb717` made `threadChanged` fetch on its own,
        // precisely so this flag would stop standing in for two things.
        if (isSameThread) {
            this.env.chatter.fetchThreadData = true;
        }
        // NOT symmetric with the above, and must stay unconditional:
        // `Thread.onWillUpdateProps` fetches the new thread's messages only
        // while this flag is up, so gating it on `isSameThread` would leave a
        // switched-to record showing no messages at all.
        this.env.chatter.fetchMessages = true;
        if (isSameThread) {
            // Both mechanisms are load-bearing despite fetching messages twice
            // on a same-record save: the flags cover renders that follow the
            // reload, while the bus event reaches the already-mounted Thread
            // whatever the render timing (e.g. for messages posted BY the save).
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
