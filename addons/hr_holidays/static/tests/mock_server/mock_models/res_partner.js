import { hrModels } from "@hr/../tests/hr_test_helpers";
import { mailDataHelpers } from "@mail/../tests/mock_server/mail_mock_server";
import { fields } from "@web/../tests/web_test_helpers";

const ON_LEAVE_STATUS = {
    away: "leave_away",
    busy: "leave_busy",
    offline: "leave_offline",
    online: "leave_online",
};

export class ResPartner extends hrModels.ResPartner {
    leave_date_to = fields.Date({ related: false });

    /**
     * @param {object} partner
     * @returns {boolean}
     */
    _is_on_leave(partner) {
        const ResUsers = this.env["res.users"];
        return ResUsers.browse(partner.user_ids ?? []).some(
            (user) => user.leave_date_to,
        );
    }

    /**
     * @param {object} partner
     * @returns {string}
     */
    compute_im_status(partner) {
        const status = super.compute_im_status(partner);
        if (!this._is_on_leave(partner)) {
            return status;
        }
        return ON_LEAVE_STATUS[status] ?? status;
    }

    get _to_store_defaults() {
        return [
            ...super._to_store_defaults,
            mailDataHelpers.Store.one(
                "main_user_id",
                mailDataHelpers.Store.many("employee_ids", "leave_date_to"),
            ),
        ];
    }
}
