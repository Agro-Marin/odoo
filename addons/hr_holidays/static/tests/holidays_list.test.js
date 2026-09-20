import { describe, expect, test } from "@odoo/hoot";
import { contains, mountView } from "@web/../tests/web_test_helpers";

import {
    defineHrHolidaysModels,
    hrHolidaysModels,
} from "./hr_holidays_test_helpers.js";

describe.current.tags("desktop");
defineHrHolidaysModels();

const LIST_ARCH = `
    <list js_class="hr_holidays_payslip_list">
        <header>
            <button name="action_approve" type="object" string="Approve"/>
            <button name="action_refuse" type="object" string="Refuse"/>
            <button name="action_other" type="object" string="Other"/>
        </header>
        <field name="can_approve" column_invisible="1"/>
        <field name="can_validate" column_invisible="1"/>
        <field name="can_refuse" column_invisible="1"/>
        <field name="state"/>
    </list>`;

test("the approve and refuse header buttons follow what the selected leaves allow", async () => {
    hrHolidaysModels.HrLeave._records = [
        { id: 1, state: "confirm", can_approve: true, can_refuse: true },
        { id: 2, state: "validate", can_approve: false, can_refuse: false },
    ];
    await mountView({ type: "list", resModel: "hr.leave", arch: LIST_ARCH });
    expect("button[name='action_approve'], button[name='action_refuse']").toHaveCount(
        0,
    );

    await contains(".o_data_row:eq(1) .o_list_record_selector input").click();
    expect("button[name='action_approve']").toHaveCount(0, {
        message: "a validated leave cannot be approved, so the button stays away",
    });
    expect("button[name='action_refuse']").toHaveCount(0);
    expect("button[name='action_other']").toHaveCount(0, {
        message: "a header button the controller has no filter for is not offered",
    });

    await contains(".o_data_row:eq(0) .o_list_record_selector input").click();
    expect("button[name='action_approve']").toHaveCount(1);
    expect("button[name='action_refuse']").toHaveCount(1);
});
