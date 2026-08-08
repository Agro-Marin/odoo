// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, onMounted, xml } from "@odoo/owl";
import {
    getMockEnv,
    makeMockEnv,
    mountWithCleanup,
} from "@web/../tests/web_test_helpers";
import { AppEvent } from "@web/core/events";
import { ActionContainer } from "@web/webclient/actions/action_container";

/**
 * COVERAGE for the render seam between the action manager and the DOM.
 *
 * Every dispatch reaches the screen through one `ACTION_MANAGER:UPDATE` event
 * carrying `{ id, Component, componentProps }`, and the container's `t-key` on
 * that `id` is what decides REMOUNT versus PATCH. That is not a detail:
 * `ActionDispatch` settles on the mount, so an id that failed to change would
 * leave a dispatch waiting on a lifecycle hook that never fires, and an id that
 * changed when it should not would throw away a controller's DOM on every
 * re-render.
 *
 * Mount counts rather than mount/unmount steps, so the harness tearing the app
 * down at the end of each test contributes nothing.
 */

describe.current.tags("desktop");

/** @type {{ mounts: number }} */
let counter;

/** A stand-in controller that reports every mount and echoes its props. */
class TestAction extends Component {
    static template = xml`<div class="o_test_action" t-att-class="props.className" t-esc="props.marker"/>`;
    static props = ["*"];
    setup() {
        onMounted(() => {
            counter.mounts++;
        });
    }
}

/** A second class, to tell "new component" apart from "new id". */
class OtherAction extends TestAction {}

async function mountContainer() {
    counter = { mounts: 0 };
    await makeMockEnv();
    return mountWithCleanup(ActionContainer, { noMainContainer: true });
}

/** Fire an `ACTION_MANAGER:UPDATE` and let the container render. */
async function update(/** @type {any} */ info) {
    getMockEnv().bus.trigger(AppEvent.ACTION_MANAGER_UPDATE, info);
    await animationFrame();
}

test("nothing is rendered until an update arrives", async () => {
    await mountContainer();

    expect(".o_action_manager").toHaveCount(1);
    expect(".o_action_manager").toHaveText("");
    expect(counter.mounts).toBe(0);
});

test("an update renders its component with the given props", async () => {
    await mountContainer();

    await update({
        id: 1,
        Component: TestAction,
        componentProps: { marker: "hello" },
    });

    expect(".o_test_action").toHaveText("hello");
    // The container names the slot it renders into; the view layer styles and
    // several suites select on it.
    expect(".o_test_action").toHaveClass("o_action");
    expect(counter.mounts).toBe(1);
});

test("a new id remounts, so the dispatch's onMounted always fires", async () => {
    await mountContainer();

    await update({ id: 1, Component: TestAction, componentProps: { marker: "first" } });
    expect(counter.mounts).toBe(1);

    // Same component class, new id: it must be torn down and mounted again,
    // because that mount is what settles the next dispatch.
    await update({
        id: 2,
        Component: TestAction,
        componentProps: { marker: "second" },
    });
    expect(".o_test_action").toHaveText("second");
    expect(counter.mounts).toBe(2);
});

test("the same id patches in place rather than remounting", async () => {
    await mountContainer();

    await update({ id: 7, Component: TestAction, componentProps: { marker: "first" } });
    expect(counter.mounts).toBe(1);

    await update({
        id: 7,
        Component: TestAction,
        componentProps: { marker: "second" },
    });
    // Props flow through, but the controller keeps its DOM: a re-render that is
    // not a new dispatch must not cost a remount.
    expect(".o_test_action").toHaveText("second");
    expect(counter.mounts).toBe(1);
});

test("a different component under the same id still remounts", async () => {
    await mountContainer();

    await update({ id: 3, Component: TestAction, componentProps: { marker: "a" } });
    expect(counter.mounts).toBe(1);

    await update({ id: 3, Component: OtherAction, componentProps: { marker: "b" } });
    expect(".o_test_action").toHaveText("b");
    expect(counter.mounts).toBe(2);
});

test("an empty payload clears the screen", async () => {
    // `ActionDispatch._restoreStack` fires this when error recovery finds no
    // controller left to display.
    await mountContainer();

    await update({ id: 1, Component: TestAction, componentProps: { marker: "x" } });
    expect(".o_test_action").toHaveCount(1);

    await update({});
    expect(".o_action_manager").toHaveText("");
    expect(".o_test_action").toHaveCount(0);
});

test("the bus listener does not outlive the container", async () => {
    // The container is destroyed and rebuilt whenever the web client is; a
    // listener left behind would render into a dead component tree on the next
    // navigation.
    const env = await makeMockEnv();
    counter = { mounts: 0 };
    const container = await mountWithCleanup(ActionContainer, {
        noMainContainer: true,
    });

    await update({ id: 1, Component: TestAction, componentProps: { marker: "a" } });
    expect(counter.mounts).toBe(1);

    const infoWhileAlive = container.info;
    container.__owl__.app.destroy();
    env.bus.trigger(AppEvent.ACTION_MANAGER_UPDATE, {
        id: 2,
        Component: TestAction,
        componentProps: { marker: "b" },
    });
    await animationFrame();

    // Asserting on the handler's own side effect, not on what it renders:
    // rendering a destroyed component is a no-op either way, so a mount count
    // cannot tell a removed listener from a retained one.
    expect(container.info).toBe(infoWhileAlive);
    expect(counter.mounts).toBe(1);
});
