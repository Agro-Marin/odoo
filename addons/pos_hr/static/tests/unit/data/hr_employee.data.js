import { models } from "@web/../tests/web_test_helpers";

export class HrEmployee extends models.ServerModel {
    _name = "hr.employee";

    // The employee's name is its party's; a seeded record without a party
    // gets one carrying its name, as the ORM would create it.
    _applyDefaults(record) {
        record.partner_id ??= this.env["res.partner"].create({ name: record.name });
        return super._applyDefaults(...arguments);
    }

    _load_pos_data_fields() {
        return ["name", "user_id", "partner_id"];
    }

    _records = [
        {
            id: 2,
            name: "Administrator",
            user_id: 2,
            partner_id: 3,
        },
        {
            id: 3,
            name: "Employee1",
            user_id: 3,
        },
    ];

    _load_pos_data_read(records) {
        records.forEach((emp) => {
            if (emp.id === 2) {
                emp._role = "manager";
            } else {
                emp._role = "cashier";
            }
        });
        return records;
    }
}
