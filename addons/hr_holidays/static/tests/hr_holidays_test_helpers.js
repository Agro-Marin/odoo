import { hrModels } from "@hr/../tests/hr_test_helpers";
import { HrDepartment } from "@hr_holidays/../tests/mock_server/mock_models/hr_department";
import { HrEmployee } from "@hr_holidays/../tests/mock_server/mock_models/hr_employee";
import { HrLeave } from "@hr_holidays/../tests/mock_server/mock_models/hr_leave";
import { HrLeaveType } from "@hr_holidays/../tests/mock_server/mock_models/hr_leave_type";
import { ResPartner } from "@hr_holidays/../tests/mock_server/mock_models/res_partner";
import { ResUsers } from "@hr_holidays/../tests/mock_server/mock_models/res_users";
import { registerMailMockRoutes } from "@mail/../tests/mock_server/mail_mock_server";
import { defineModels, defineParams } from "@web/../tests/web_test_helpers";

export function defineHrHolidaysModels() {
    // Bind mail's mock-server routes to the calling suite; without this every
    // /mail/* call in an hr_holidays test answers {}.
    registerMailMockRoutes();
    defineParams({ suite: "hr_holidays" }, "replace");
    return defineModels(hrHolidaysModels);
}

export const hrHolidaysModels = {
    ...hrModels,
    ResUsers,
    ResPartner,
    HrEmployee,
    HrDepartment,
    HrLeaveType,
    HrLeave,
};
