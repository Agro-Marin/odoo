import {
    click,
    contains,
    defineMailModels,
    insertText,
    openFormView,
    patchUiSize,
    scroll,
    SIZES,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { mockService, serverState } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineMailModels();

test.skip("Form view not scrolled when switching record", async () => {
    // FIXME: test passed in test environment but in practice scroll are reset to 0
    // HOOT matches behaviour in prod and shows tests not passing as expected
    const pyEnv = await startServer();
    const [partnerId_1, partnerId_2] = pyEnv["res.partner"].create([
        {
            description: [...Array(60).keys()].join("\n"),
            display_name: "Partner 1",
        },
        {
            description: [...Array(60).keys()].join("\n"),
            display_name: "Partner 2",
        },
    ]);
    const messages = [...Array(60).keys()].map((id) => ({
        body: "not empty",
        model: "res.partner",
        res_id: id < 29 ? partnerId_1 : partnerId_2,
    }));
    pyEnv["mail.message"].create(messages);
    patchUiSize({ size: SIZES.LG });
    await start();
    await openFormView("res.partner", partnerId_1, {
        arch: `
            <form string="Partners">
                <sheet>
                    <field name="name"/>
                    <field name="description"/>
                </sheet>
                <chatter/>
            </form>`,
        resIds: [partnerId_1, partnerId_2],
    });
    await contains(".o-mail-Message", { count: 29 });
    await contains(".o_content", { scroll: 0 });
    await scroll(".o_content", 150);
    await click(".o_pager_next");
    await contains(".o-mail-Message", { count: 30 });
    await contains(".o_content", { scroll: 150 });
    await scroll(".o_content", 0);
    await click(".o_pager_previous");
    await contains(".o-mail-Message", { count: 29 });
    await contains(".o_content", { scroll: 0 });
});

test("Attachments that have been unlinked from server should be visually unlinked from record", async () => {
    const pyEnv = await startServer();
    const [partnerId_1, partnerId_2] = pyEnv["res.partner"].create([
        { display_name: "Partner1" },
        { display_name: "Partner2" },
    ]);
    const [attachmentId_1] = pyEnv["ir.attachment"].create([
        {
            mimetype: "text.txt",
            res_id: partnerId_1,
            res_model: "res.partner",
        },
        {
            mimetype: "text.txt",
            res_id: partnerId_1,
            res_model: "res.partner",
        },
    ]);
    await start();
    await openFormView("res.partner", partnerId_1, {
        arch: `
            <form string="Partners">
                <sheet>
                    <field name="name"/>
                </sheet>
                <chatter/>
            </form>`,
        resId: partnerId_1,
        resIds: [partnerId_1, partnerId_2],
    });
    await contains("button[aria-label='Attach files']", { text: "2" });
    // The attachment links are updated on (re)load,
    // so using pager is a way to reload the record "Partner1".
    await click(".o_pager_next");
    await contains("button[aria-label='Attach files']:not(:has(sup))");
    // Simulate unlinking attachment 1 from Partner 1.
    pyEnv["ir.attachment"].write([attachmentId_1], { res_id: 0 });
    await click(".o_pager_previous");
    await contains("button[aria-label='Attach files']", { text: "1" });
});

test("ellipsis button is not duplicated when switching from read to edit mode", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({});
    pyEnv["mail.message"].create({
        author_id: partnerId,
        // "data-o-mail-quote" added by server is intended to be compacted in ellipsis block
        body: `
            <div>
                Dear Joel Willis,<br>
                Thank you for your enquiry.<br>
                If you have any questions, please let us know.
                <br><br>
                Thank you,<br>
                <div data-o-mail-quote="1">-- <br data-o-mail-quote="1">
                    System
                </div>
            </div>`,
        model: "res.partner",
        res_id: partnerId,
    });
    await start();
    await openFormView("res.partner", partnerId, {
        arch: `
            <form string="Partners">
                <sheet>
                    <field name="name"/>
                </sheet>
                <chatter/>
            </form>`,
    });
    await contains(".o-mail-Chatter");
    await contains(".o-mail-Message");
    await contains(".o-mail-ellipsis");
});

test("[TECHNICAL] unfolded ellipsis button should not fold on message click besides that button", async () => {
    // a message click re-renders: re-inserting the ellipsis buttons there would
    // re-fold them, e.g. when the click comes from selecting text to copy
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ display_name: "Someone" });
    pyEnv["mail.message"].create({
        author_id: partnerId,
        // "data-o-mail-quote" added by server is intended to be compacted in ellipsis block
        body: `
            <div>
                Dear Joel Willis,<br>
                Thank you for your enquiry.<br>
                If you have any questions, please let us know.
                <br><br>
                Thank you,<br>
                <span data-o-mail-quote="1">-- <br data-o-mail-quote="1">
                    System
                </span>
            </div>`,
        model: "res.partner",
        res_id: partnerId,
    });
    await start();
    await openFormView("res.partner", partnerId, {
        arch: `
            <form string="Partners">
                <sheet>
                    <field name="name"/>
                </sheet>
                <chatter/>
            </form>`,
    });
    expect(".o-mail-Message-body span").toHaveCount(0);
    await click(".o-mail-ellipsis");
    expect(".o-mail-Message-body span").toHaveText("--\nSystem");
    await click(".o-mail-Message");
    expect(".o-mail-Message-body span").toHaveCount(1);
});

test("ellipsis button on message of type notification", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({});
    pyEnv["mail.message"].create({
        author_id: partnerId,
        // "data-o-mail-quote" enables ellipsis block
        body: `
            <div>
                Dear Joel Willis,<br>
                Thank you for your enquiry.<br>
                If you have any questions, please let us know.
                <br><br>
                Thank you,<br>
                <span data-o-mail-quote="1">-- <br data-o-mail-quote="1">
                    System
                </span>
            </div>`,
        model: "res.partner",
        res_id: partnerId,
        message_type: "notification",
    });
    await start();
    await openFormView("res.partner", partnerId, {
        arch: `
            <form string="Partners">
                <sheet>
                    <field name="name"/>
                </sheet>
                <chatter/>
            </form>`,
    });
    await contains(".o-mail-ellipsis");
});

test("read more/less should appear only once for the signature", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({});

    mockService("action", {
        doAction(action, { onClose }) {
            if (action.name === "Compose Email") {
                // Simulate message post of full composer
                pyEnv["mail.message"].create({
                    body: action.context.default_body.toString(),
                    model: action.context.default_model,
                    res_id: action.context.default_res_ids[0],
                });
                return onClose(undefined);
            }
            return super.doAction(...arguments);
        },
    });

    // the html editor can produce this kind of quote-marked signature
    pyEnv["res.users"].write(serverState.userId, {
        signature: `
            <div>
                <span data-o-mail-quote="1">
                    --
                </span>
            </div>
            <div data-o-mail-quote="1">
                Signature !
            </div>
            <div>
                <br data-o-mail-quote="1">
            </div>
        `,
    });

    await start();
    await openFormView("res.partner", partnerId);
    await contains(".o-mail-Chatter");
    await click(".o-mail-Chatter-sendMessage");
    await insertText(".o-mail-Composer-input", "Example Body");
    await click("[name='open-full-composer']");
    await contains(".o-mail-Message-body", { text: "Example Body", count: 1 });
    expect(".o-mail-Message .o-signature-container button.o-mail-ellipsis").toHaveCount(
        1,
    );
});
