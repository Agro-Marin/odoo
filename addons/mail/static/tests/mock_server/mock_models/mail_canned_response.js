// @ts-check
import { mailDataHelpers } from "@mail/../tests/mock_server/mail_mock_server";
import { getKwArgs, makeKwArgs, models } from "@web/../tests/web_test_helpers";

export class MailCannedResponse extends models.ServerModel {
    _name = "mail.canned.response";

    _views = {
        list: `
            <list>
                <field name="source" widget="shortcut"/>
            </list>
        `,
        form: `
            <form>
                <field name="source" widget="shortcut"/>
            </form>
        `,
        kanban: `
            <kanban>
                <templates>
                    <t t-name="card">
                        <field name="source" widget="shortcut"/>
                    </t>
                </templates>
            </kanban>
        `,
    };

    /** @param {Parameters<import("@web/../tests/_framework/mock_server/mock_model").Model["create"]>} args */
    create(...args) {
        const cannedReponseIds = super.create(...args);
        this._broadcast(cannedReponseIds);
        return cannedReponseIds;
    }

    write(ids, values) {
        const res = super.write(ids, values);
        this._broadcast(ids);
        return res;
    }

    unlink(ids) {
        this._broadcast(ids, makeKwArgs({ delete: true }));
        return super.unlink(ids);
    }

    _broadcast(ids, _delete) {
        const kwargs = getKwArgs(arguments, "ids", "delete");
        _delete = kwargs.delete;
        const notifications = [];
        const [partner] = this.env["res.partner"].read(this.env.user.partner_id);
        for (const cannedResponse of this.browse(ids)) {
            notifications.push([
                partner,
                "mail.record/insert",
                new mailDataHelpers.Store(
                    this.browse(cannedResponse.id),
                    makeKwArgs({ delete: _delete }),
                ).get_result(),
            ]);
        }
        if (notifications.length) {
            this.env["bus.bus"]._sendmany(notifications);
        }
    }

    get _to_store_defaults() {
        return ["source", "substitution"];
    }
}
