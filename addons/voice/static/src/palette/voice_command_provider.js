// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";

export const VOICE_NAMESPACE = ">";

registry.category("command_setup").add(VOICE_NAMESPACE, {
    name: _t("sentences"),
    placeholder: _t("Say it in words: unpaid, group by salesperson…"),
    emptyMessage: _t("Not understood. Try a filter, a field or a menu name."),
});

registry.category("command_provider").add("voice", {
    namespace: VOICE_NAMESPACE,
    async provide(env, { searchValue }) {
        const text = searchValue.trim();
        if (!text) {
            return [];
        }
        const voice = env.services.voice;
        const interpretation = voice.interpret(text, { withTargets: false });
        const proposals = interpretation.candidates.length
            ? interpretation.candidates
            : interpretation.proposals;
        return proposals.map((/** @type {any} */ proposal) => ({
            name: proposal.description,
            action: () => voice.accept(text, proposal),
        }));
    },
});
