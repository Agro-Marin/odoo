import { mailModels } from "@mail/../tests/mail_test_helpers";
import { fields } from "@web/../tests/web_test_helpers";

export class ResFake extends mailModels.ResFake {
    duration = fields.Float({ string: "duration" });
    // `mrp_timer` prefers the live duration while a record is in progress, and
    // falls back to the bound field when the view does not load it.
    duration_live = fields.Float({ string: "duration_live" });
    state = fields.Char({ string: "state" });
    is_user_working = fields.Boolean({ string: "is_user_working" });

    _views = {
        form: /* xml */ `
            <form>
                <field name="duration" widget="mrp_timer" readonly="1"/>
            </form>`,
        "form,live": /* xml */ `
            <form>
                <field name="state" invisible="1"/>
                <field name="duration_live" invisible="1"/>
                <field name="duration" widget="mrp_timer" readonly="1"/>
            </form>`,
    };
}
