// @ts-check

import { expect, onError, test } from "@odoo/hoot";
import { click, hover, leave, waitFor } from "@odoo/hoot-dom";
import { advanceTime, animationFrame, runAllTimers } from "@odoo/hoot-mock";
import { Component, markup, xml } from "@odoo/owl";
import {
    getService,
    makeMockEnv,
    mountWithCleanup,
} from "@web/../tests/web_test_helpers";
import { MainComponentsContainer } from "@web/components/main_components_container";
import { registry } from "@web/core/registry";
import { NotificationContainer } from "@web/ui/notification/notification_container";
import { notificationService } from "@web/ui/notification/notification_service";

test("can display a basic notification", async () => {
    await makeMockEnv();
    const { Component: NotificationContainer, props } = registry
        .category("main_components")
        .get("NotificationContainer");
    await mountWithCleanup(NotificationContainer, { props, noMainContainer: true });
    getService("notification").add("I'm a basic notification");
    await animationFrame();
    expect(".o_notification").toHaveCount(1);
    expect(".o_notification_content").toHaveText("I'm a basic notification");
    expect(".o_notification_bar").toHaveClass("bg-warning");
});

test("can display a notification with a className", async () => {
    await makeMockEnv();
    const { Component: NotificationContainer, props } = registry
        .category("main_components")
        .get("NotificationContainer");
    await mountWithCleanup(NotificationContainer, { props, noMainContainer: true });
    getService("notification").add("I'm a basic notification", { className: "abc" });
    await animationFrame();
    expect(".o_notification.abc").toHaveCount(1);
});

test("message are escaped by default", async () => {
    await makeMockEnv();
    const { Component: NotificationContainer, props } = registry
        .category("main_components")
        .get("NotificationContainer");
    await mountWithCleanup(NotificationContainer, { props, noMainContainer: true });
    getService("notification").add("<i>Some message</i>");
    await animationFrame();
    expect(".o_notification").toHaveCount(1);
    expect(".o_notification_content").toHaveText("<i>Some message</i>");
});

test("can display a notification with markup content", async () => {
    await makeMockEnv();
    const { Component: NotificationContainer, props } = registry
        .category("main_components")
        .get("NotificationContainer");
    await mountWithCleanup(NotificationContainer, { props, noMainContainer: true });
    getService("notification").add(markup`<b>I'm a <i>markup</i> notification</b>`);
    await animationFrame();
    expect(".o_notification").toHaveCount(1);
    expect(".o_notification_content").toHaveInnerHTML(
        "<b>I'm a <i>markup</i> notification</b>",
    );
});

test("can display a notification with title and markup content", async () => {
    await makeMockEnv();
    const { Component: NotificationContainer, props } = registry
        .category("main_components")
        .get("NotificationContainer");
    await mountWithCleanup(NotificationContainer, { props, noMainContainer: true });
    getService("notification").add(markup`<b>I'm a <i>markup</i> notification</b>`, {
        title: "I'm a title",
    });
    await animationFrame();
    expect(".o_notification").toHaveCount(1);
    expect(".o_notification_content").toHaveInnerHTML(
        "I'm a title. <b>I'm a <i>markup</i> notification</b>",
    );
    expect(".o_notification_content").toHaveText(
        "I'm a title. I'm a markup notification",
    );
});

test("can display a notification of type danger", async () => {
    await makeMockEnv();
    const { Component: NotificationContainer, props } = registry
        .category("main_components")
        .get("NotificationContainer");
    await mountWithCleanup(NotificationContainer, { props, noMainContainer: true });
    getService("notification").add("I'm a danger notification", { type: "danger" });
    await animationFrame();
    expect(".o_notification").toHaveCount(1);
    expect(".o_notification_content").toHaveText("I'm a danger notification");
    expect(".o_notification_bar").toHaveClass("bg-danger");
});

test("can display a notification with a button", async () => {
    await makeMockEnv();
    const { Component: NotificationContainer, props } = registry
        .category("main_components")
        .get("NotificationContainer");
    await mountWithCleanup(NotificationContainer, { props, noMainContainer: true });
    getService("notification").add("I'm a notification with button", {
        buttons: [
            {
                name: "I'm a button",
                onClick: () => {
                    expect.step("Button clicked");
                },
            },
        ],
    });
    await animationFrame();
    expect(".o_notification").toHaveCount(1);
    expect(".o_notification_buttons").toHaveText("I'm a button");
    await click(".o_notification .btn-link");
    await animationFrame();
    expect.verifySteps(["Button clicked"]);
    expect(".o_notification").toHaveCount(1);
});

test("can display a notification with a callback when closed", async () => {
    await makeMockEnv();
    const { Component: NotificationContainer, props } = registry
        .category("main_components")
        .get("NotificationContainer");
    await mountWithCleanup(NotificationContainer, { props, noMainContainer: true });
    getService("notification").add("I'm a sticky notification", {
        sticky: true,
        onClose: () => {
            expect.step("Notification closed");
        },
    });
    await animationFrame();
    expect(".o_notification").toHaveCount(1);
    await click(".o_notification .o_notification_close");
    await animationFrame();
    expect.verifySteps(["Notification closed"]);
    expect(".o_notification").toHaveCount(0);
});

test("notifications aren't sticky by default", async () => {
    await makeMockEnv();
    const { Component: NotificationContainer, props } = registry
        .category("main_components")
        .get("NotificationContainer");
    await mountWithCleanup(NotificationContainer, { props, noMainContainer: true });
    getService("notification").add("I'm a notification");
    await animationFrame();
    expect(".o_notification").toHaveCount(1);
    await advanceTime(4000);
    await animationFrame();
    expect(".o_notification").toHaveCount(0);
});

test("can display a sticky notification", async () => {
    await makeMockEnv();
    const { Component: NotificationContainer, props } = registry
        .category("main_components")
        .get("NotificationContainer");
    await mountWithCleanup(NotificationContainer, { props, noMainContainer: true });
    getService("notification").add("I'm a sticky notification", { sticky: true });
    await animationFrame();
    expect(".o_notification").toHaveCount(1);
    await advanceTime(5000);
    await animationFrame();
    expect(".o_notification").toHaveCount(1);
});

test("can close sticky notification", async () => {
    await makeMockEnv();
    const { Component: NotificationContainer, props } = registry
        .category("main_components")
        .get("NotificationContainer");
    await mountWithCleanup(NotificationContainer, { props, noMainContainer: true });
    const closeNotif = getService("notification").add("I'm a sticky notification", {
        sticky: true,
    });
    await animationFrame();
    expect(".o_notification").toHaveCount(1);

    closeNotif();
    await animationFrame();
    expect(".o_notification").toHaveCount(0);

    getService("notification").add("I'm a sticky notification", { sticky: true });
    await animationFrame();
    expect(".o_notification").toHaveCount(1);

    await click(".o_notification .o_notification_close");
    await animationFrame();
    expect(".o_notification").toHaveCount(0);
});

test.skip("can close sticky notification with wait", async () => {
    await makeMockEnv();
    const { Component: NotificationContainer, props } = registry
        .category("main_components")
        .get("NotificationContainer");
    await mountWithCleanup(NotificationContainer, { props, noMainContainer: true });
    const closeNotif = getService("notification").add("I'm a sticky notification", {
        sticky: true,
    });
    await animationFrame();
    expect(".o_notification").toHaveCount(1);

    getService("notification").close(closeNotif, 3000);
    await animationFrame();
    expect(".o_notification").toHaveCount(1);

    await advanceTime(3000);
    await animationFrame();
    expect(".o_notification").toHaveCount(0);
});

test("can close a non-sticky notification", async () => {
    await makeMockEnv();
    const { Component: NotificationContainer, props } = registry
        .category("main_components")
        .get("NotificationContainer");
    await mountWithCleanup(NotificationContainer, { props, noMainContainer: true });
    const closeNotif = getService("notification").add("I'm a sticky notification");
    await animationFrame();
    expect(".o_notification").toHaveCount(1);

    closeNotif();
    await animationFrame();
    expect(".o_notification").toHaveCount(0);

    await runAllTimers();
    expect(".o_notification").toHaveCount(0);
});

test.tags("desktop");
test("can refresh the duration of a non-sticky notification", async () => {
    await makeMockEnv();
    const { Component: NotificationContainer, props } = registry
        .category("main_components")
        .get("NotificationContainer");
    await mountWithCleanup(NotificationContainer, { props, noMainContainer: true });
    getService("notification").add("I'm a first non-sticky notification");
    getService("notification").add("I'm a second non-sticky notification");
    await animationFrame();
    expect(".o_notification").toHaveCount(2);

    await advanceTime(3000);
    await hover(".o_notification:first-child");
    await advanceTime(5000);
    expect(".o_notification").toHaveCount(1);
    await leave();
    await advanceTime(3000);
    expect(".o_notification").toHaveCount(1);
    await advanceTime(2000);
    expect(".o_notification").toHaveCount(0);
});

test("close a non-sticky notification while another one remains", async () => {
    await makeMockEnv();
    const { Component: NotificationContainer, props } = registry
        .category("main_components")
        .get("NotificationContainer");
    await mountWithCleanup(NotificationContainer, { props, noMainContainer: true });
    const closeNotif1 = getService("notification").add("I'm a non-sticky notification");
    const closeNotif2 = getService("notification").add("I'm a sticky notification", {
        sticky: true,
    });
    await animationFrame();
    expect(".o_notification").toHaveCount(2);

    closeNotif1();
    await animationFrame();
    expect(".o_notification").toHaveCount(1);

    await runAllTimers();
    expect(".o_notification").toHaveCount(1);

    closeNotif2();
    await animationFrame();
    expect(".o_notification").toHaveCount(0);
});

test("notification coming when NotificationManager not mounted yet", async () => {
    await makeMockEnv();
    const { Component: NotificationContainer, props } = registry
        .category("main_components")
        .get("NotificationContainer");
    mountWithCleanup(NotificationContainer, { props, noMainContainer: true });
    getService("notification").add("I'm a non-sticky notification");
    await animationFrame();
    expect(".o_notification").toHaveCount(1);
});

test("notification autocloses after a specified delay", async () => {
    await makeMockEnv();
    const { Component: NotificationContainer, props } = registry
        .category("main_components")
        .get("NotificationContainer");

    await mountWithCleanup(NotificationContainer, { props, noMainContainer: true });
    getService("notification").add("custom autoclose delay notification", {
        autocloseDelay: 1000,
    });

    await waitFor(".o_notification");
    await advanceTime(500);
    await animationFrame();
    expect(".o_notification").toHaveCount(1);

    await advanceTime(500);
    await animationFrame();
    expect(".o_notification").toHaveCount(0);
});

test("a notification that fails to render does not kill later notifications", async () => {
    expect.errors(1);
    onError((error) => expect.step(error.reason.message));

    await makeMockEnv();
    await mountWithCleanup(MainComponentsContainer);

    getService("notification").add("faulty", { buttons: "not-a-list" });
    await animationFrame();
    await animationFrame();
    expect.verifySteps([
        "Invalid props for component 'Notification': 'buttons' is not a list of objects",
    ]);
    expect.verifyErrors([
        "Invalid props for component 'Notification': 'buttons' is not a list of objects",
    ]);

    getService("notification").add("I still work");
    await animationFrame();
    expect(".o_notification").toHaveCount(1);
    expect(".o_notification_content").toHaveText("I still work");
});

test("an unrecognised option does not cost the caller their notification", async () => {
    // Every option used to be spread straight into props, so a single unknown
    // key made Owl reject the component and the container dropped the toast --
    // and only in debug mode, where prop validation runs, i.e. exactly when a
    // developer is looking.
    await mountWithCleanup(MainComponentsContainer);

    getService("notification").add("first");
    await animationFrame();
    expect(".o_notification").toHaveCount(1);

    getService("notification").add("second", { notAnOption: true });
    await animationFrame();
    await animationFrame();
    expect(".o_notification").toHaveCount(2);
});

test("known options still reach the notification", async () => {
    await mountWithCleanup(MainComponentsContainer);
    getService("notification").add("styled", {
        type: "success",
        className: "o_custom_notif",
        sticky: true,
        title: "Heads up",
    });
    await animationFrame();
    expect(".o_notification.o_custom_notif").toHaveCount(1);
    expect(".o_notification_bar.bg-success").toHaveCount(1);
    expect(".o_notification").toHaveText(/Heads up/);
});

test("a subclassed container still receives its own extra props", async () => {
    // `website_sale` swaps in a CartNotification taking `lines`/`warning`/
    // `currency_id`. The allow-list must come from the hosted component's own
    // `props`, never a fixed list in the service, or the subclass loses
    // exactly the props it exists for.
    class CustomNotification extends Component {
        static template = xml`<div class="o_custom_notif" t-esc="props.flavour"/>`;
        static props = {
            message: { type: String },
            flavour: { type: String },
            className: { type: String, optional: true },
            close: { type: Function },
        };
    }
    class CustomContainer extends NotificationContainer {
        static components = {
            ...NotificationContainer.components,
            Notification: CustomNotification,
        };
    }
    const customService = {
        ...notificationService,
        notificationContainer: CustomContainer,
        notificationContainerKey: "CustomNotificationContainer",
    };
    registry.category("services").add("custom_notification", customService);

    const env = await makeMockEnv();
    await mountWithCleanup(MainComponentsContainer, { env });

    env.services.custom_notification.add("hello", { flavour: "mango" });
    await animationFrame();
    expect(".o_custom_notif").toHaveCount(1);
    expect(".o_custom_notif").toHaveText("mango");
});
