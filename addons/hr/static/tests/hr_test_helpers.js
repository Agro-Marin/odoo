import { FakeUser } from "@hr/../tests/mock_server/mock_models/fake_user";
import { HrDepartment } from "@hr/../tests/mock_server/mock_models/hr_department";
import { HrEmployee } from "@hr/../tests/mock_server/mock_models/hr_employee";
import { HrEmployeePublic } from "@hr/../tests/mock_server/mock_models/hr_employee_public";
import { M2xAvatarEmployee } from "@hr/../tests/mock_server/mock_models/m2x_avatar_employee";
import { mailModels } from "@mail/../tests/mail_test_helpers";
import { ResourceResource } from "@resource/../tests/mock_server/mock_models/resource_resource";
import { defineModels, onRpc } from "@web/../tests/web_test_helpers";

import { HrJob } from "./mock_server/mock_models/hr_job.js";
import { HrVersion } from "./mock_server/mock_models/hr_version.js";
import { HrWorkLocation } from "./mock_server/mock_models/hr_work_location.js";
import { ResPartner } from "./mock_server/mock_models/res_partner.js";
import { ResUsers } from "./mock_server/mock_models/res_users.js";

export function defineHrModels() {
    onRpc("get_avatar_card_data", function getAvatarCardData({ args }) {
        const employeeId = args[0][0];
        const employees = this.env["hr.employee.public"].search_read([
            ["id", "=", employeeId],
        ]);
        return employees.map((employee) => ({
            name: employee.name,
            work_email: employee.work_email,
            phone: employee.phone,
            user_id: employee.user_id,
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
    HrEmployeePublic,
    FakeUser,
    HrJob,
    HrWorkLocation,
    ResourceResource,
    ResUsers,
    ResPartner,
};
