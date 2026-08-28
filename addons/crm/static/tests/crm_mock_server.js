import { luxon } from "@web/core/l10n/luxon";
import { deserializeDateTime } from "@web/core/l10n/dates";

/**
 * Mock of `crm.lead.get_rainbowman_message`, exported rather than registered.
 *
 * It used to register itself, and the ONE consumer registered a second handler
 * on top to record a step and chain through `parent()`. `_findOrmListeners`
 * unshifts each match, so the LAST registration runs FIRST -- and this one was
 * last, being inside a global `beforeEach` while the consumer's sat at module
 * level. So it answered the call itself and the consumer's `expect.step` never
 * ran: thirteen of `crm_rainbowman.test.js`'s tests failed on
 * `[verifySteps] Received: []` while the rainbow man itself rendered correctly.
 *
 * Exporting it removes the ordering coupling instead of reversing it. Call it
 * with the mock server as `this`, which an `onRpc` callback already receives.
 *
 * @this {import("@web/../tests/web_test_helpers").MockServer}
 */
export function getRainbowmanMessage({ args, model }) {
    let message = false;
    if (model !== "crm.lead") {
        return message;
    }
    const records = this.env["crm.lead"];
    const record = records.browse(args[0])[0];
    const won_stage = this.env["crm.stage"].search_read([["is_won", "=", true]])[0];
    if (
        record.stage_id === won_stage.id &&
        record.user_id &&
        record.team_id &&
        record.planned_revenue > 0
    ) {
        const now = luxon.DateTime.now();
        const query_result = {};
        // Total won
        query_result["total_won"] = records.filter(
            (r) => r.stage_id === won_stage.id && r.user_id === record.user_id,
        ).length;
        // Max team 30 days
        const recordsTeam30 = records.filter(
            (r) =>
                r.stage_id === won_stage.id &&
                r.team_id === record.team_id &&
                (!r.date_closed ||
                    now.diff(deserializeDateTime(r.date_closed)).as("days") <= 30),
        );
        query_result["max_team_30"] = Math.max(
            ...recordsTeam30.map((r) => r.planned_revenue),
        );
        // Max team 7 days
        const recordsTeam7 = records.filter(
            (r) =>
                r.stage_id === won_stage.id &&
                r.team_id === record.team_id &&
                (!r.date_closed ||
                    now.diff(deserializeDateTime(r.date_closed)).as("days") <= 7),
        );
        query_result["max_team_7"] = Math.max(
            ...recordsTeam7.map((r) => r.planned_revenue),
        );
        // Max User 30 days
        const recordsUser30 = records.filter(
            (r) =>
                r.stage_id === won_stage.id &&
                r.user_id === record.user_id &&
                (!r.date_closed ||
                    now.diff(deserializeDateTime(r.date_closed)).as("days") <= 30),
        );
        query_result["max_user_30"] = Math.max(
            ...recordsUser30.map((r) => r.planned_revenue),
        );
        // Max User 7 days
        const recordsUser7 = records.filter(
            (r) =>
                r.stage_id === won_stage.id &&
                r.user_id === record.user_id &&
                (!r.date_closed ||
                    now.diff(deserializeDateTime(r.date_closed)).as("days") <= 7),
        );
        query_result["max_user_7"] = Math.max(
            ...recordsUser7.map((r) => r.planned_revenue),
        );

        if (query_result.total_won === 1) {
            message = "Go, go, go! Congrats for your first deal.";
        } else if (query_result.max_team_30 === record.planned_revenue) {
            message = "Boom! Team record for the past 30 days.";
        } else if (query_result.max_team_7 === record.planned_revenue) {
            message = "Yeah! Best deal out of the last 7 days for the team.";
        } else if (query_result.max_user_30 === record.planned_revenue) {
            message = "You just beat your personal record for the past 30 days.";
        } else if (query_result.max_user_7 === record.planned_revenue) {
            message = "You just beat your personal record for the past 7 days.";
        }
    }
    return message;
}
