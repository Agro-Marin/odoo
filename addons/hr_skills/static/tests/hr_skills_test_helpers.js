import { hrModels } from "@hr/../tests/hr_test_helpers";
import { defineModels } from "@web/../tests/web_test_helpers";

import { HrEmployeeSkill } from "./mock_server/mock_models/hr_employee_skill.js";
import { HrResumeLine } from "./mock_server/mock_models/hr_resume_line.js";
import { HrResumeLineType } from "./mock_server/mock_models/hr_resume_line_type.js";
import { HrSkill } from "./mock_server/mock_models/hr_skill.js";
import { M2oAvatarEmployee } from "./mock_server/mock_models/m2o_avatar_employee.js";

export function defineHrSkillModels() {
    return defineModels(hrSkillModels);
}

export const hrSkillModels = {
    ...hrModels,
    HrEmployeeSkill,
    HrResumeLine,
    HrResumeLineType,
    HrSkill,
    M2oAvatarEmployee,
};
