import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { waitForChannels, waitNotifications } from "@bus/../tests/bus_test_helpers";
import { hrModels } from "@hr/../tests/hr_test_helpers";
import { MockServer, defineModels, models, mountView } from "@web/../tests/web_test_helpers";
import { serverState } from "@web/../tests/_framework/mock_server_state.hoot";

class HrEmployee extends models.ServerModel {
    _name = "hr.employee";
    _records = [
        {
            id: 22,
            name: "Alfredo Absent",
            hr_icon_display: "presence_absent",
            hr_presence_state: "absent",
            user_id: serverState.userId,
        },
    ];
    _views = {
        search: `<search><field name="display_name"/></search>`,
        list: `<list><field name="hr_icon_display" widget="hr_presence_status"/></list>`,
    };
}

defineModels({ ...hrModels, HrEmployee });

test.tags("desktop");
test("presence icon follows a check-in without reloading the view", async () => {
    await mountView({ resModel: "hr.employee", type: "list" });
    await waitForChannels(["hr.employee_22"]);
    expect(".o_employee_availability [role=img]").toHaveAttribute("title", "Absent");

    MockServer.env["bus.bus"]._sendone("hr.employee_22", "hr.employee/presence", {
        employee_id: 22,
        hr_presence_state: "present",
        hr_icon_display: "presence_present",
    });
    await waitNotifications(["hr.employee/presence"]);
    await animationFrame();
    expect(".o_employee_availability [role=img]").toHaveAttribute("title", "Present");
});
