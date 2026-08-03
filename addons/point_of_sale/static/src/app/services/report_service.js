/** @odoo-module native */
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { downloadReport } from "@web/webclient/actions";
export const reportService = {
    dependencies: ["ui", "orm", "pos"],
    start(env, { ui, orm, pos }) {
        const reportActionsCache = {};
        return {
            async doAction(reportXmlId, active_ids) {
                ui.block();
                try {
                    // Evict the cache entry if the load fails, otherwise a single
                    // transient rejection is memoized and re-thrown forever for that
                    // report.
                    reportActionsCache[reportXmlId] ||= rpc("/web/action/load", {
                        action_id: reportXmlId,
                    }).catch((error) => {
                        delete reportActionsCache[reportXmlId];
                        throw error;
                    });
                    const reportAction = await reportActionsCache[reportXmlId];
                    // await instead of return because we want the ui to stay blocked
                    await downloadReport(
                        { ...reportAction, context: { active_ids } },
                        "pdf",
                        user.context,
                    );
                } finally {
                    ui.unblock();
                }
            },
        };
    },
};

registry.category("services").add("report", reportService);
