/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { downloadReport } from "@web/webclient/actions";
const log = makeLogger("pos.report");
export const reportService = {
    dependencies: ["ui", "orm", "pos"],
    start(env, { ui, orm, pos }) {
        const reportActionsCache = {};
        return {
            async doAction(reportXmlId, active_ids) {
                ui.block();
                const endReport = log.perf(`[report] ${reportXmlId}`);
                log.pipeline("[report] doAction", () => ({
                    reportXmlId,
                    active_ids,
                    cached: Boolean(reportActionsCache[reportXmlId]),
                }));
                try {
                    reportActionsCache[reportXmlId] ||= rpc("/web/action/load", {
                        action_id: reportXmlId,
                    }).catch((error) => {
                        delete reportActionsCache[reportXmlId];
                        throw error;
                    });
                    const reportAction = await reportActionsCache[reportXmlId];
                    await downloadReport(
                        { ...reportAction, context: { active_ids } },
                        "pdf",
                        user.context,
                    );
                } finally {
                    ui.unblock();
                    endReport({ reportXmlId, records: active_ids?.length });
                }
            },
        };
    },
};

registry.category("services").add("report", reportService);
