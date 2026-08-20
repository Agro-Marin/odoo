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
    triggerHotkey,
} from "@mail/../tests/mail_test_helpers";
import { HIGHLIGHT_CLASS } from "@mail/core/common/message_search_hook";
import { describe, test } from "@odoo/hoot";
import { patchWithCleanup, serverState } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineMailModels();

test("Chatter should display search icon", async () => {
    const pyEnv = await startServer();
    patchUiSize({ size: SIZES.XXL });
    await start();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    await openFormView("res.partner", partnerId);
    await contains("[title='Search Messages']");
});

test("Click on the search icon should open the search form", async () => {
    const pyEnv = await startServer();
    patchUiSize({ size: SIZES.XXL });
    await start();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    await openFormView("res.partner", partnerId);
    await click("[title='Search Messages']");
    await contains(".o_searchview");
    await contains(".o_searchview_input");
});

test("Search in chatter", async () => {
    patchUiSize({ size: SIZES.XXL });
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    pyEnv["mail.message"].create({
        body: "not empty",
        model: "res.partner",
        res_id: partnerId,
    });
    await start();
    await openFormView("res.partner", partnerId);
    await click("[title='Search Messages']");
    await insertText(".o_searchview_input", "empty");
    triggerHotkey("Enter");
    await contains(".o-mail-SearchMessageResult .o-mail-Message");
    await click(".o-mail-MessageCard-jump");
    await contains(".o-mail-Message.o-highlighted .o-mail-Message-content", {
        text: "not empty",
    });
});

test("Close button should close the search panel", async () => {
    patchUiSize({ size: SIZES.XXL });
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    pyEnv["mail.message"].create({
        body: "not empty",
        model: "res.partner",
        res_id: partnerId,
    });
    await start();
    await openFormView("res.partner", partnerId);
    await click(".o-mail-Chatter-topbar [title='Search Messages']");
    await insertText(".o_searchview_input", "empty");
    triggerHotkey("Enter");
    await contains(".o-mail-SearchMessageResult .o-mail-Message");
    await click(".o-mail-SearchMessageInput [title='Close']");
    await contains(".o-mail-SearchMessageInput", { count: 0 });
});

test("Search in chatter should be hightligted", async () => {
    patchUiSize({ size: SIZES.XXL });
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    pyEnv["mail.message"].create({
        body: "not empty",
        model: "res.partner",
        res_id: partnerId,
    });
    await start();
    await openFormView("res.partner", partnerId);
    await click("[title='Search Messages']");
    await insertText(".o_searchview_input", "empty");
    triggerHotkey("Enter");
    await contains(`.o-mail-SearchMessageResult .o-mail-Message .${HIGHLIGHT_CLASS}`);
});

test("Scrolling bottom in non-aside chatter should load more searched message", async () => {
    patchUiSize({ size: SIZES.LG });
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    for (let i = 0; i < 60; i++) {
        pyEnv["mail.message"].create({
            author_id: serverState.partnerId,
            body: "This is a message",
            attachment_ids: [],
            message_type: "comment",
            model: "res.partner",
            res_id: partnerId,
        });
    }
    await start();
    await openFormView("res.partner", partnerId);
    await click("[title='Search Messages']");
    await insertText(".o_searchview_input", "message");
    triggerHotkey("Enter");
    await contains(".o-mail-SearchMessageResult .o-mail-Message", { count: 30 });
    await scroll(".o_content", "bottom");
    await contains(".o-mail-SearchMessageResult .o-mail-Message", { count: 60 });
});

test("Search result count renders exactly when the server did not cap it", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    for (let i = 0; i < 3; i++) {
        pyEnv["mail.message"].create({
            author_id: serverState.partnerId,
            body: "This is a message",
            attachment_ids: [],
            message_type: "comment",
            model: "res.partner",
            res_id: partnerId,
        });
    }
    await start();
    await openFormView("res.partner", partnerId);
    await click("[title='Search Messages']");
    await insertText(".o_searchview_input", "message");
    triggerHotkey("Enter");
    await contains(".o-mail-SearchMessageResult", { text: "3 messages found" });
});

test("Search result count renders as N+ when the server says it capped", async () => {
    // The cap lives on the server (`mail.message._SEARCH_COUNT_CAP`); the client
    // is told *that* it bit, never the number. Holding a second copy of 1000
    // here is what this test exists to prevent, so the cap is patched rather
    // than reproduced -- the python twin patches the same attribute.
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    for (let i = 0; i < 3; i++) {
        pyEnv["mail.message"].create({
            author_id: serverState.partnerId,
            body: "This is a message",
            attachment_ids: [],
            message_type: "comment",
            model: "res.partner",
            res_id: partnerId,
        });
    }
    patchWithCleanup(pyEnv["mail.message"], { _search_count_cap: 2 });
    await start();
    await openFormView("res.partner", partnerId);
    await click("[title='Search Messages']");
    await insertText(".o_searchview_input", "message");
    triggerHotkey("Enter");
    await contains(".o-mail-SearchMessageResult", { text: "2+ messages found" });
});
