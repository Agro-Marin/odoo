// @ts-check
/** @odoo-module native */

import { markup } from "@odoo/owl";
import { Dictation } from "@speech/live_capture/dictation";
import { user } from "@web/core/user";
import { escape } from "@web/core/utils/format/strings";
import { voiceExecutorRegistry } from "@voice/executor";

/**
 * @param {any} before
 * @param {string} said
 * @param {string} fieldType
 */
export function withDictated(before, said, fieldType) {
    if (!said) {
        return before || "";
    }
    if (fieldType === "html") {
        return markup(`${before || ""}<p>${escape(said)}</p>`);
    }
    return before ? `${before} ${said}` : said;
}

/**
 * Words arrive per chunk, and out of order; each lands where it was said, and
 * the field shows everything heard so far after what it held before.
 *
 * @param {import("@voice/interpreter/interpreter").Proposal} proposal
 * @param {import("@voice/executor").ExecutionContext} context
 */
export async function dictate(proposal, context) {
    const record = context.targetView(proposal).controller.model.root;
    const { fieldName, fieldType } = proposal;
    const before = record.data[fieldName];
    /** @type {string[]} */
    const heard = [];
    const dictation = new Dictation({
        orm: context.getService("orm"),
        bus: context.getService("bus_service"),
        onChunkSent: () => {},
        onChunkText: (index, text) => {
            heard[index] = text.trim();
            record.update({
                [fieldName]: withDictated(
                    before,
                    heard.filter(Boolean).join(" "),
                    fieldType,
                ),
            });
        },
        onError: (error) => context.report(error?.message || String(error)),
    });
    await dictation.start({
        resModel: record.resModel,
        resId: record.resId || undefined,
        language: (user.lang || "en").split("-")[0].split("_")[0],
        prompt: record.data.display_name || "",
    });
    context.startSession({ label: proposal.description, stop: () => dictation.stop() });
    return () => record.update({ [fieldName]: before });
}

voiceExecutorRegistry.add("dictate", dictate);
