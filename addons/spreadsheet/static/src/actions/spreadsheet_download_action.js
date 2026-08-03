/** @odoo-module native */
import { createSpreadsheetModel, waitForDataLoaded } from "@spreadsheet/helpers/model";
import { download } from "@web/core/network";
import { registry } from "@web/core/registry";

/**
 * @param {import("@web/env").OdooEnv} env
 * @param {object} action
 */
async function downloadSpreadsheet(env, action) {
    let { name, data, stateUpdateMessages, xlsxData } = action.params;
    if (!xlsxData) {
        const model = await createSpreadsheetModel({ env, data, revisions: stateUpdateMessages });
        await waitForDataLoaded(model);
        xlsxData = model.exportXLSX();
    }
    await download({
        url: "/spreadsheet/xlsx",
        data: {
            zip_name: `${name}.xlsx`,
            files: new Blob([JSON.stringify(xlsxData.files)], { type: "application/json" }),
        },
    });
}

registry
    .category("actions")
    .add("action_download_spreadsheet", downloadSpreadsheet, { force: true });
