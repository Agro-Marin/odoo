/** @odoo-module native */
import { _t } from "@web/core/l10n/translation";
import { useOwnedDialogs, useService } from "@web/core/utils/hooks";
import { SelectCreateDialog } from "@web/views/view_dialogs/select_create_dialog";

/**
 * Open the "Select Packages to Move" dialog and, on confirmation, add the chosen
 * entire packages to `pickingId` then soft-reload the view.
 *
 * Shared by the picking-form moves list (`stock_move_one2many`) and the
 * add-package list view (`stock_add_package_list_view`) so the dialog config and
 * the action_add_entire_packs -> soft_reload flow live in one place.
 *
 * @param {Object} p
 * @param {Function} p.addDialog owned-dialog opener (useOwnedDialogs())
 * @param {Object} p.orm orm service
 * @param {Object} p.actionService action service
 * @param {number} p.pickingId picking the packages are added to
 * @param {number} [p.locationId] restrict the selectable packages to this location
 */
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
            // Guard pickingId too: without a real picking the server would
            // browse(0) and silently no-op.
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

/**
 * Hook wiring the services `openSelectPackagesDialog` needs (owned dialogs, orm,
 * action). Returns `open(pickingId, locationId)`. Must be called from a
 * component setup(). Lets each renderer keep only how it derives the ids rather
 * than re-wiring the same three services and re-building the same param object.
 */
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
