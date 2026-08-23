import { fields, models } from "@web/../tests/web_test_helpers";

export class ApprovalCategory extends models.ServerModel {
    _name = "approval.category";

    name = fields.Char();
    active = fields.Boolean({ default: true });

    _views = {
        kanban: `
            <kanban js_class="approvals_category_kanban">
                <templates>
                    <t t-name="card">
                        <field name="name"/>
                    </t>
                </templates>
            </kanban>`,
    };
}
