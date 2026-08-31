import { hrModels } from "@hr/../tests/hr_test_helpers";
import { mailDataHelpers } from "@mail/../tests/mock_server/mail_mock_server";
import { fields } from "@web/../tests/web_test_helpers";

/**
 * How a presence status reads once the partner is on leave, mirroring
 * `hr_holidays/models/res_partner.py::_compute_presence`. A status absent from
 * this map is left alone, exactly as the `elif` ladder there leaves it.
 */
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
     * Base status first, then the leave mapping over it -- the order the server
     * uses (`super()._compute_presence()` then the `elif` ladder).
     *
     * This is a second implementation of a server computation, and it had
     * drifted from it in three ways at once. It read `leave_date_to` off
     * `ResUsers.browse(...)`, which is a *recordset*: the field came back
     * `undefined` on every call, so the leave branch never once fired and no
     * partner was ever on leave in a JS test. It consulted `main_user_id`
     * alone where the server joins over every user. And its `else` swept
     * `busy` -- and anything else -- into `leave_offline`, so `leave_busy`
     * could not be produced at all, though `store_service_patch` lists it
     * among the online statuses.
     *
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
