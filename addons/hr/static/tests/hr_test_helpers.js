import { FakeUser } from "@hr/../tests/mock_server/mock_models/fake_user";
import { HrDepartment } from "@hr/../tests/mock_server/mock_models/hr_department";
import { HrEmployee } from "@hr/../tests/mock_server/mock_models/hr_employee";
import { M2xAvatarEmployee } from "@hr/../tests/mock_server/mock_models/m2x_avatar_employee";
import { mailModels } from "@mail/../tests/mail_test_helpers";
import { registerMailMockRoutes } from "@mail/../tests/mock_server/mail_mock_server";
import { ResourceResource } from "@resource/../tests/mock_server/mock_models/resource_resource";
import { defineModels, defineParams, onRpc } from "@web/../tests/web_test_helpers";

import { HrJob } from "./mock_server/mock_models/hr_job.js";
import { HrVersion } from "./mock_server/mock_models/hr_version.js";
import { HrWorkLocation } from "./mock_server/mock_models/hr_work_location.js";
import { ResPartner } from "./mock_server/mock_models/res_partner.js";
import { ResUsers } from "./mock_server/mock_models/res_users.js";

export function defineHrModels() {
    // hrModels spreads mailModels, so hr's suites speak to mail's store; the
    // routes that serve it are registered separately and only on request (see
    // registerMailMockRoutes). Without this call /mail/action reaches no
    // handler, and a request that asked to resolve itself -- getChat's
    // /discuss/get_or_create_chat -- comes back in a payload carrying no
    // DataResponse, so the chat window never opens.
    registerMailMockRoutes();
    defineParams({ suite: "hr" }, "replace");
    onRpc("get_formview_action", function getFormviewAction({ args, model }) {
        return {
            type: "ir.actions.act_window",
            res_model: model,
            res_id: args[0][0],
            views: [[false, "form"]],
        };
    });
    onRpc("get_avatar_card_data", function getAvatarCardData({ args }) {
        // The mock employee stores its channels as work_email/work_phone; on
        // the server they are the party's email and phone.
        const fieldNames = [
            ...new Set([
                ...(args[1] || []),
                "name",
                "work_email",
                "work_phone",
                "email",
                "phone",
                "user_id",
            ]),
        ];
        return this.env["hr.employee"].read(args[0], fieldNames).map((employee) => ({
            ...employee,
            email: employee.work_email || employee.email,
            phone: employee.work_phone || employee.phone,
            share: false,
        }));
    });
    return defineModels(hrModels);
}

export const hrModels = {
    ...mailModels,
    M2xAvatarEmployee,
    HrDepartment,
    HrEmployee,
    HrVersion,
    FakeUser,
    HrJob,
    HrWorkLocation,
    ResourceResource,
    ResUsers,
    ResPartner,
};
