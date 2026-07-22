import { mailModels } from "@mail/../tests/mail_test_helpers";
import { animationFrame } from "@odoo/hoot-mock";
import { setupInteractionWhiteList } from "@web/../tests/public/helpers";
import { registry } from "@web/core/registry";
import { buildEditableInteractions } from "@website/core/website_edit_service";

import { Website } from "./mock_server/mock_models/website.js";
import { WebsiteVisitor } from "./mock_server/mock_models/website_visitor.js";

export async function switchToEditMode(core) {
    core.stopInteractions();
    const activeInteractions = setupInteractionWhiteList.getWhiteList();
    const unmatchedInteractions = activeInteractions
        ? new Set(activeInteractions)
        : new Set();
    const builders = registry.category("public.interactions.edit").getEntries();
    // Shallow-copy the non-white-listed entries instead of flagging them
    // `isAbstract` in place. The registry is global and lives for the whole
    // browser session, so an in-place flag was never undone: the first `.edit`
    // suite to run marked every interaction outside *its* white list abstract,
    // and each later suite then found its own interaction already abstract and
    // silently never built it. That is why the `.edit` suites passed in
    // isolation and failed in a full `@website/interactions` run.
    // `buildEditableInteractions` still receives every entry -- it needs the
    // complete set to resolve the mixins of ancestor classes -- but only these
    // throw-away copies carry the test-local `isAbstract`.
    const Interactions = builders.map(([key, builder]) => {
        unmatchedInteractions.delete(key);
        return activeInteractions && !activeInteractions.includes(key)
            ? { ...builder, isAbstract: true }
            : builder;
    });
    if (unmatchedInteractions.size) {
        throw new Error(
            `White-listed Interaction does not exist: ${[...unmatchedInteractions]}.`,
        );
    }
    const editableInteractions = buildEditableInteractions(Interactions);
    core.activate(editableInteractions);
    await animationFrame();
}

export const websiteModels = {
    ...mailModels,
    Website,
    WebsiteVisitor,
};
