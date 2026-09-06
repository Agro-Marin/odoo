import { mailDataHelpers } from "@mail/../tests/mock_server/mail_mock_server";
import { fields, models } from "@web/../tests/web_test_helpers";

export class HrEmployee extends models.ServerModel {
    _name = "hr.employee";

    department_id = fields.Many2one({ relation: "hr.department" });
    work_email = fields.Char();
    work_phone = fields.Char();
    work_location_type = fields.Char();
    work_location_id = fields.Many2one({ relation: "hr.work.location" });
    job_title = fields.Char();

    // The employee delegates to its party and reads active and user_id off its
    // resource; the server-backed mock follows those definitions, so a fixture
    // that gives only a name would read nameless, inactive and userless. The
    // mock mints the party and the resource the way the ORM does, for records
    // created by a test and for a module's seeded _records alike.
    _mintDelegates(values) {
        values.partner_id ??= this.env["res.partner"].create({
            name: values.name,
            email: values.work_email ?? values.email ?? false,
            phone: values.work_phone ?? values.phone ?? false,
        });
        values.resource_id ??= this.env["resource.resource"].create({
            name: values.name,
            active: values.active ?? true,
            user_id: values.user_id ?? false,
        });
    }

    _applyDefaults(record) {
        this._mintDelegates(record);
        return super._applyDefaults(...arguments);
    }

    create(vals) {
        for (const values of Array.isArray(vals) ? vals : [vals]) {
            this._mintDelegates(values);
        }
        return super.create(...arguments);
    }

    write(ids, values) {
        if ("user_id" in values || "active" in values) {
            const resourceIds = this.read(ids, ["resource_id"])
                .map((employee) => employee.resource_id && employee.resource_id[0])
                .filter(Boolean);
            const resourceValues = {};
            if ("user_id" in values) {
                resourceValues.user_id = values.user_id;
            }
            if ("active" in values) {
                resourceValues.active = values.active;
            }
            this.env["resource.resource"].write(resourceIds, resourceValues);
        }
        return super.write(...arguments);
    }

    _get_fields_store_avatar_card() {
        return [
            "company_id",
            mailDataHelpers.Store.one("department_id", ["name"]),
            "work_email",
            mailDataHelpers.Store.one("work_location_id", ["location_type", "name"]),
            "work_phone",
            "job_title",
        ];
    }

    _views = {
        search: `<search><field name="display_name" string="Name" /></search>`,
        list: `<list><field name="display_name"/></list>`,
    };
}
