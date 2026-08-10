import { expect, test, describe, beforeEach } from "@odoo/hoot";
import { click, queryText } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";

import { contains, mountWithCleanup, onRpc } from "@web/../tests/web_test_helpers";

import { ActivityMenu } from "@mail/core/web/activity_menu";
import { triggerHotkey } from "@mail/../tests/mail_test_helpers";

import { defineTodoModels } from "./todo_test_helpers.js";
import { MailActivityTodoCreate } from "./mock_server/mock_models/mail_activity_todo_create.js";

describe.current.tags("desktop");
defineTodoModels();

beforeEach(() => {
    MailActivityTodoCreate._views = {
        form: `
            <form>
                <group>
                    <field name="summary" default_focus="1" placeholder="Reminder to..." required="1"/>
                    <field name="date_deadline"/>
                    <field name="user_id" widget="many2one_avatar_user" options="{'no_open': 1}"/>
                </group>
                <footer>
                    <button class="btn btn-primary" type="object" name="create_todo_activity" close="1">Add To-Do</button>
                    <button class="btn btn-secondary" special="cancel" close="1">Discard</button>
                </footer>
            </form>`,
    };
});

test("the wizard opens on an unsaved record, so nothing is left behind on discard", async () => {
    onRpc("mail.activity.todo.create", "web_save", () => expect.step("web_save"));
    await mountWithCleanup(ActivityMenu);

    await triggerHotkey("control+k");
    await animationFrame();
    await click(`.o_command:contains("Add a To-Do")`);
    await animationFrame();

    expect(".modal-dialog .o_field_widget[name='summary']").toHaveCount(1);
    // Opening the dialog must not have written anything: the old implementation
    // RPC-created the transient record first, orphaning a row on every cancel.
    expect.verifySteps([]);
});

test("summary is focused when the wizard opens", async () => {
    await mountWithCleanup(ActivityMenu);

    await triggerHotkey("control+k");
    await animationFrame();
    await click(`.o_command:contains("Add a To-Do")`);
    await animationFrame();

    expect(".modal-dialog .o_field_widget[name='summary'] input").toBeFocused({
        message: "default_focus on summary should place the cursor in the dialog",
    });
});

test("global shortcut", async () => {
    onRpc(
        "/web/dataset/call_button/mail.activity.todo.create/create_todo_activity",
        () => true,
    );
    onRpc("mail.activity.todo.create", "web_save", ({ args }) =>
        expect.step(args[1].summary),
    );
    await mountWithCleanup(ActivityMenu);
    await triggerHotkey("control+k");
    await animationFrame();
    expect(queryText(`.o_command:contains("Add a To-Do") .o_command_hotkey`)).toEqual(
        "Add a To-Do\nALT + SHIFT + T",
        { message: "The command should be registered with the right hotkey" },
    );

    await triggerHotkey("alt+shift+t");
    await contains(".modal-dialog .o_field_widget[name='summary'] .o_input").edit(
        "My first todo",
    );
    await click(".modal-dialog .btn.btn-primary:contains(Add To-Do)");
    // The save RPC resolves asynchronously after the click.
    await animationFrame();
    expect.verifySteps(["My first todo"]);
});
