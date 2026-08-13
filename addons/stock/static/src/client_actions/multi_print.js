/** @odoo-module native */
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";

async function doMultiPrint(env, action) {
    for (const report of action.params.reports) {
        if (report.type !== "ir.actions.report") {
            env.services.notification.add(
                _t("Incorrect type of action submitted as a report, skipping action"),
                {
                    title: _t("Report Printing Error"),
                },
            );
            continue;
        } else if (report.report_type === "qweb-html") {
            env.services.notification.add(
                _t(
                    "HTML reports cannot be auto-printed, skipping report: %s",
                    report.name,
                ),
                { title: _t("Report Printing Error") },
            );
            continue;
        }
        try {
            await env.services.action.doAction({
                type: "ir.actions.report",
                ...report,
            });
        } catch {
            env.services.notification.add(
                _t("Could not print report: %s", report.name),
                { title: _t("Report Printing Error") },
            );
        }
    }
    if (action.params.anotherAction) {
        return env.services.action.doAction(action.params.anotherAction);
    } else if (action.params.onClose) {
        return action.params.onClose();
    } else {
        return env.services.action.doAction("reload_context");
    }
}

registry.category("actions").add("do_multi_print", doMultiPrint);
