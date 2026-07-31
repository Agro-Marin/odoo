import { expect, onError, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import {
    getService,
    makeMockEnv,
    mountWithCleanup,
} from "@web/../tests/web_test_helpers";
import { CartNotificationContainer } from "@website_sale/js/notification/notification_service";

/** A cart toast that throws while rendering, the way a missing `lines` does. */
class Boom extends Component {
    static props = ["*"];
    static template = xml`<div t-esc="props.missing.length"/>`;
}

/** The cart container, wired to the base notification service for the test. */
class TestCartContainer extends CartNotificationContainer {
    static serviceName = "notification";
    static components = { ...CartNotificationContainer.components, Notification: Boom };
}

test("a throwing cart toast does not take the whole container down with it", async () => {
    // The base `web.NotificationContainer` template wraps its loop in an
    // `ErrorHandler`; this container overrides the template and used to drop
    // it. The throw then escaped the container itself, so on a real page
    // `MainComponentsContainer` unregistered it and every later cart toast for
    // the session was silently lost. `CartNotification` dereferences its own
    // OPTIONAL `lines` prop, so that is one missing key away.
    expect.errors(1);
    onError(() => expect.step("contained"));

    await makeMockEnv();
    await mountWithCleanup(TestCartContainer, { noMainContainer: true });
    expect(".pe-none").toHaveCount(1);

    getService("notification").add("boom");
    await animationFrame();
    await animationFrame();

    expect.verifySteps(["contained"]);
    expect.verifyErrors([/Cannot read properties of undefined/]);
    expect(".pe-none").toHaveCount(1, {
        message: "the container survived the toast that threw",
    });
});
