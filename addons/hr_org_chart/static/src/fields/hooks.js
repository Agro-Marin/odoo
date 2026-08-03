/** @odoo-module native */
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { rpc } from "@web/core/network";
import { useService } from "@web/core/utils/hooks";

/**
 * Build a click handler that redirects to the subordinate employees kanban view.
 *
 * @returns {Function} async click handler
 */
export function onEmployeeSubRedirect() {
    const actionService = useService('action');
    const orm = useService('orm');

    return async (event) => {
        const employeeId = parseInt(event.currentTarget.dataset.employeeId);
        if (!employeeId) {
            return {};
        }
        const type = event.currentTarget.dataset.type || 'direct';
        // Get subordinates of an employee through a rpc call.
        const subordinateIds = await rpc('/hr/get_subordinates', {
            employee_id: employeeId,
            subordinates_type: type,
            context: user.context
        });
        let action = await orm.call('hr.employee', 'get_formview_action', [employeeId]);
        action = {...action,
            name: _t('Team'),
            view_mode: 'kanban,list,form',
            views: [[false, 'kanban'], [false, 'list'], [false, 'form']],
            domain: [['id', 'in', subordinateIds]],
            res_id: false,
            context: {
                default_parent_id: employeeId,
            }
        };
        actionService.doAction(action);
    };
}
