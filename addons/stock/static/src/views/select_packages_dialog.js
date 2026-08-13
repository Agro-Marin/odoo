/** @odoo-module native */
import { _t } from "@web/core/translation";
import { useOwnedDialogs, useService } from "@web/core/utils/hooks";
import { SelectCreateDialog } from "@web/views/view_dialogs";

export function openSelectPackagesDialog({
    addDialog,
    orm,
    actionService,
    pickingId,
    locationId,
}) {
    const domain = [];
    if (locationId) {
        domain.push(["location_id", "child_of", locationId]);
    }
    addDialog(SelectCreateDialog, {
        title: _t("Select Packages to Move"),
        noCreate: true,
        multiSelect: true,
        resModel: "stock.package",
        domain,
        context: {
            list_view_ref: "stock.view_stock_package_list_add",
        },
        onSelected: async (resIds) => {
            if (!resIds.length || !pickingId) {
                return;
            }
            const done = await orm.call("stock.picking", "action_add_entire_packs", [
                [pickingId],
                resIds,
            ]);
            if (done) {
                await actionService.doAction({
                    type: "ir.actions.client",
                    tag: "soft_reload",
                });
            }
        },
    });
}

export function useMovePackageDialog() {
    const addDialog = useOwnedDialogs();
    const orm = useService("orm");
    const actionService = useService("action");
    return (pickingId, locationId) =>
        openSelectPackagesDialog({
            addDialog,
            orm,
            actionService,
            pickingId,
            locationId,
        });
}
