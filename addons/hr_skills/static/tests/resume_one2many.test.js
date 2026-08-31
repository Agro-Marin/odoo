import {
    defineHrSkillModels,
    hrSkillModels,
} from "@hr_skills/../tests/hr_skills_test_helpers";
import { contains } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { mountView, onRpc } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineHrSkillModels();

const RESUME_ARCH = `
    <form>
        <field mode="list" nolabel="1" name="resume_line_ids" widget="resume_one2many">
            <list>
                <field name="line_type_id"/>
                <field name="name"/>
                <field name="date_start"/>
                <field name="date_end"/>
            </list>
        </field>
    </form>`;

// The row template calls api.formatDate(...). web hands the row helpers to a row
// COMPONENT as its `api` prop; this renderer calls the row template directly, so
// `api` has to be bound in the calling scope. When it was not, rendering an
// employee that holds any resume line threw "Cannot read properties of undefined
// (reading 'formatDate')" and took the form down -- a crash the tour caught only
// at step 12 of 36, and only as an OwlError with the selector of a later step.
test("resume_one2many renders a stored line", async () => {
    const { HrEmployee, HrResumeLine, HrResumeLineType } = hrSkillModels;
    const typeId = HrResumeLineType._records.length + 1;
    HrResumeLineType._records.push({ id: typeId, name: "Experience" });
    const lineId = HrResumeLine._records.length + 1;
    HrResumeLine._records.push({
        id: lineId,
        name: "Mamie Rock",
        line_type_id: typeId,
        date_start: "2020-01-01",
        date_end: "2021-01-01",
    });
    const employeeId = HrEmployee._records.length + 1;
    HrEmployee._records.push({
        id: employeeId,
        name: "Jony McHallyFace",
        resume_line_ids: [lineId],
    });
    onRpc("hr.employee", "get_internal_resume_lines", () => []);

    await mountView({
        type: "form",
        resModel: "hr.employee",
        resId: employeeId,
        arch: RESUME_ARCH,
    });

    await contains(".o_field_resume_one2many");
    expect(".o_resume_line_title").toHaveCount(1);
    expect(".o_resume_line_title").toHaveText("Mamie Rock");
    expect(".o_resume_line_dates").toHaveCount(1);
});
