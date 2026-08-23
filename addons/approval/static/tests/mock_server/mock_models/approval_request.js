import { models } from "@web/../tests/web_test_helpers";

export class ApprovalRequest extends models.ServerModel {
    _name = "approval.request";
    _views = {
        form: `
            <form>
                <chatter/>
            </form>`,
        list: `
            <list>
                <field name="display_name"/>
                <field name="activity_ids" widget="list_activity"/>
            </list>`,
    };
}
