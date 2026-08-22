import { openFormView, start, startServer } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { defineModels, models } from "@web/../tests/web_test_helpers";

import { defineAccountModels } from "./account_test_helpers.js";

describe.current.tags("desktop");

class MailAlias extends models.ServerModel {
    _name = "mail.alias";
}

defineAccountModels();
defineModels({ MailAlias });

const ARCH = `
    <form>
        <field name="type" invisible="1"/>
        <field name="alias_email" invisible="1"/>
        <widget name="bill_upload_guide"/>
    </form>`;

describe("BillGuide alias", () => {
    test("links to the journal alias when the journal has one", async () => {
        const pyEnv = await startServer();
        const aliasId = pyEnv["mail.alias"].create({
            alias_full_name: "bills@test.example.com",
        });
        const journalId = pyEnv["account.journal"].create({
            name: "Vendor Bills",
            type: "purchase",
            alias_id: aliasId,
        });
        await start();

        await openFormView("account.journal", journalId, { arch: ARCH });

        expect("a[href^='mailto:']").toHaveCount(1);
        expect("a[href^='mailto:']").toHaveText("bills@test.example.com");
        expect(".o_invoice_new").toHaveCount(0);
    });

    test("falls back to manual creation when the journal has no alias", async () => {
        const pyEnv = await startServer();
        const journalId = pyEnv["account.journal"].create({
            name: "Vendor Bills",
            type: "purchase",
        });
        await start();

        await openFormView("account.journal", journalId, { arch: ARCH });

        expect("a[href^='mailto:']").toHaveCount(0);
        expect(".o_invoice_new").toHaveCount(1);
    });
});
