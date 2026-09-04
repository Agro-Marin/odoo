import { models } from "@web/../tests/web_test_helpers";

export class HrEmployee extends models.ServerModel {
    _name = "hr.employee";

    _load_pos_data_fields() {
        return ["name", "user_id", "work_contact_id"];
    }

    _records = [
        {
            id: 2,
            name: "Administrator",
            user_id: 2,
            work_contact_id: 3,
        },
        {
            id: 3,
            name: "Employee1",
            user_id: 3,
            work_contact_id: 3,
        },
        {
            id: 4,
            name: "Employee2",
        },
    ];

    _load_pos_data_read(records) {
        const rolesById = { 2: "manager", 4: "minimal" };
        records.forEach((emp) => {
            emp._role = rolesById[emp.id] || "cashier";
        });
        return records;
    }
}
