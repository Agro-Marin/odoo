// @ts-check

import { expect, onError, test } from "@odoo/hoot";
import { queryAll, queryOne, resize } from "@odoo/hoot-dom";
import { animationFrame, mockTouch, runAllTimers } from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import {
    defineActions,
    defineModels,
    fields,
    getService,
    makeMockEnv,
    models,
    mountWebClient,
    mountWithCleanup,
    onRpc,
    patchWithCleanup,
    webModels,
} from "@web/../tests/web_test_helpers";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { ConfirmationDialog } from "@web/ui/dialog/confirmation_dialog";
import { Dialog } from "@web/ui/dialog/dialog";
import { RainbowMan } from "@web/ui/effects/rainbow_man";
import { MainComponentsContainer } from "@web/ui/main_components_container";
import { makeOverlayPresenter } from "@web/ui/overlay/presenter";
import {
    getDetachedTargetObserverCount,
    watchForDetachedTarget,
} from "@web/ui/popover/detached_target_watcher";
import { Popover } from "@web/ui/popover/popover";
import { usePopover } from "@web/ui/popover/popover_hook";

class Partner extends models.Model {
    name = fields.Char();
    _records = [
        { id: 1, name: "p1" },
        { id: 2, name: "p2" },
    ];
    _views = {
        list: `<list><field name="name"/></list>`,
        search: `<search/>`,
    };
}
defineModels({ ...webModels, Partner });
defineActions([
    { id: 1, name: "Partners", res_model: "partner", views: [[false, "list"]] },
]);

class Content extends Component {
    static template = xml`<div class="popover-content"/>`;
    static props = ["*"];
}

class DialogContent extends Component {
    static template = xml`<Dialog title="'t'"><div class="dlg-body"/></Dialog>`;
    static components = { Dialog };
    static props = ["*"];
}

// A bottom sheet used to push a bare history entry, so dismissing one looked
// like a browser navigation: the webclient re-ran loadState and refetched the
// records behind the sheet.
test.tags("mobile");
test("closing a mobile dropdown does not reload the action behind it", async () => {
    mockTouch(true);
    await resize({ width: 375, height: 667 });

    /** @type {string[]} */
    const calls = [];
    let recording = false;
    onRpc(({ model, method }) => {
        if (recording) {
            calls.push(`${model}.${method}`);
        }
    });

    await mountWebClient();
    await getService("action").doAction(1);
    await animationFrame();
    await runAllTimers();
    expect(".o_list_view").toHaveCount(1);
    const controllerBefore = getService("action").currentController?.jsId;

    recording = true;
    // The first .o-dropdown of this layout is not visible; take the one that
    // actually produces a sheet.
    for (const toggle of queryAll(".o-dropdown")) {
        toggle.click();
        await animationFrame();
        await animationFrame();
        if (queryAll(".o_bottom_sheet").length) {
            break;
        }
    }
    expect(".o_bottom_sheet").toHaveCount(1);

    queryOne(".o_bottom_sheet_backdrop").click();
    await animationFrame();
    await runAllTimers();
    await animationFrame();
    await runAllTimers();
    recording = false;

    expect(".o_bottom_sheet").toHaveCount(0);
    expect(calls).toEqual([]);
    expect(getService("action").currentController?.jsId).toBe(controllerBefore);
});

// usePopover used to resolve its backend once, in setup(). Its only caller
// derives the choice from a media query, and a breakpoint change does not
// remount a component — so a rotated tablet kept opening desktop popovers.
let wantSheet = false;
class SheetHost extends Component {
    static template = xml`<div class="host"/>`;
    static props = ["*"];
    setup() {
        this.popover = usePopover(Content, { useBottomSheet: () => wantSheet });
    }
}

test("usePopover re-reads useBottomSheet on every open", async () => {
    await makeMockEnv();
    wantSheet = false;
    const host = await mountWithCleanup(SheetHost);

    host.popover.open(queryOne(".host"), {});
    await animationFrame();
    expect(".o_bottom_sheet").toHaveCount(0);
    expect(".o_popover").toHaveCount(1);
    host.popover.close();
    await animationFrame();

    // The screen got small after setup ran.
    wantSheet = true;
    host.popover.open(queryOne(".host"), {});
    await animationFrame();
    expect(".o_bottom_sheet").toHaveCount(1);
    expect(".o_popover").toHaveCount(0);
});

test("Dropdown follows the breakpoint without being remounted", async () => {
    mockTouch(true);
    await resize({ width: 1366, height: 768 });
    class Host extends Component {
        static components = { Dropdown };
        static props = ["*"];
        static template = xml`
            <Dropdown>
                <button class="dd-toggle">t</button>
                <t t-set-slot="content"><span class="dd-item">i</span></t>
            </Dropdown>`;
    }
    await makeMockEnv();
    await mountWithCleanup(Host);
    await animationFrame();

    queryOne(".dd-toggle").click();
    await animationFrame();
    expect(".o_bottom_sheet").toHaveCount(0);
    queryOne(".dd-toggle").click();
    await animationFrame();

    await resize({ width: 375, height: 667 });
    await runAllTimers();
    await animationFrame();

    queryOne(".dd-toggle").click();
    await animationFrame();
    await animationFrame();
    expect(".o_bottom_sheet").toHaveCount(1);
});

// Every Popover used to install its own document-wide subtree MutationObserver
// just to notice its anchor leaving the DOM. Tooltips open popovers on hover,
// so ordinary mouse travel armed and disarmed one per hovered element.
test("popovers share one detached-target observer per root", async () => {
    await makeMockEnv();
    class Host extends Component {
        static props = ["*"];
        static template = xml`
            <div>
                <div class="t1">1</div><div class="t2">2</div><div class="t3">3</div>
            </div>`;
    }
    await mountWithCleanup(Host);
    expect(getDetachedTargetObserverCount()).toBe(0);

    // Counting live map entries is not enough: a per-watcher observer that
    // overwrites its map slot would leave the count at 1 while still taxing
    // every DOM mutation three times over. Count the observe() calls.
    let observeCalls = 0;
    let disconnectCalls = 0;
    const Native = MutationObserver;
    patchWithCleanup(globalThis, {
        MutationObserver: class extends Native {
            observe(...args) {
                observeCalls++;
                return super.observe(...args);
            }
            disconnect() {
                disconnectCalls++;
                return super.disconnect();
            }
        },
    });

    const disposers = [
        watchForDetachedTarget(queryOne(".t1"), () => {}),
        watchForDetachedTarget(queryOne(".t2"), () => {}),
        watchForDetachedTarget(queryOne(".t3"), () => {}),
    ];
    expect(observeCalls).toBe(1);
    expect(getDetachedTargetObserverCount()).toBe(1);

    for (const dispose of disposers) {
        dispose();
    }
    expect(getDetachedTargetObserverCount()).toBe(0);
    expect(disconnectCalls).toBe(1);
});

test("a popover still closes when its target leaves the DOM", async () => {
    await makeMockEnv();
    class Host extends Component {
        static props = ["*"];
        static template = xml`<div class="wrap"><div class="anchor">a</div></div>`;
    }
    await mountWithCleanup(Host);
    const target = queryOne(".anchor");
    await mountWithCleanup(Popover, {
        props: { component: Content, target, close: () => expect.step("closed") },
    });
    await animationFrame();
    expect.verifySteps([]);

    target.remove();
    await animationFrame();
    await animationFrame();
    expect.verifySteps(["closed"]);
});

// The rainbow man closed on any body click, so the documented custom-Component
// API could not hold anything the user was meant to interact with.
test("a hosted rainbowman component keeps its clicks", async () => {
    class Hosted extends Component {
        static template = xml`<button class="rm-btn" t-on-click="onClick">go</button>`;
        static props = ["*"];
        onClick() {
            expect.step("button");
        }
    }
    await mountWithCleanup(RainbowMan, {
        props: {
            fadeout: "no",
            close: () => expect.step("closed"),
            message: "hi",
            imgUrl: "/web/static/img/smile.svg",
            Component: Hosted,
            props: {},
        },
    });
    await animationFrame();
    queryOne(".rm-btn").click();
    await animationFrame();
    expect.verifySteps(["button"]);

    // Clicking outside the card still dismisses it.
    document.body.click();
    await animationFrame();
    expect.verifySteps(["closed"]);
});

test("a message-only rainbowman still closes on any click", async () => {
    await mountWithCleanup(RainbowMan, {
        props: {
            fadeout: "no",
            close: () => expect.step("closed"),
            message: "well done",
            imgUrl: "/web/static/img/smile.svg",
        },
    });
    await animationFrame();
    queryOne(".o_reward_msg_content").click();
    await animationFrame();
    expect.verifySteps(["closed"]);
});

// A dialog stays mounted until its onClose settles (a button action reloading
// the view keeps it up on purpose), but the wait used to be invisible and every
// further click on the close button was swallowed by the re-entrancy guard.
test.tags("desktop");
test("a dialog waiting on a slow onClose says so instead of looking stuck", async () => {
    await makeMockEnv();
    await mountWithCleanup(MainComponentsContainer);

    /** @type {(v?: any) => void} */
    let release = () => {};
    const slow = new Promise((r) => (release = r));
    getService("dialog").add(DialogContent, {}, { onClose: () => slow });
    await animationFrame();
    expect(".o_dialog").toHaveCount(1);
    expect(".o_dialog_closing").toHaveCount(0);
    expect(".o_dialog .btn-close").not.toHaveAttribute("disabled");

    queryOne(".o_dialog .btn-close").click();
    await animationFrame();
    await animationFrame();

    expect(".o_dialog").toHaveCount(1);
    expect(".o_dialog_closing").toHaveCount(1);
    expect(".o_dialog .btn-close").toHaveAttribute("disabled");

    release();
    await animationFrame();
    await animationFrame();
    expect(".o_dialog").toHaveCount(0);
});

// The footer buttons are declared in ConfirmationDialog's own template; the
// disabled state that guards against double submits belongs there too, not in
// a querySelectorAll over the rendered modal.
test.tags("desktop");
test("confirmation dialog disables its buttons declaratively", async () => {
    await makeMockEnv();
    await mountWithCleanup(MainComponentsContainer);

    /** @type {(v?: any) => void} */
    let release = () => {};
    const slow = new Promise((r) => (release = r));
    getService("dialog").add(ConfirmationDialog, {
        body: "sure?",
        confirm: () => slow,
        cancel: () => {},
    });
    await animationFrame();
    expect(".modal-footer button:not([disabled])").toHaveCount(2);

    queryOne(".modal-footer button:first").click();
    await animationFrame();
    expect(".modal-footer button[disabled]").toHaveCount(2);

    release();
    await animationFrame();
    await animationFrame();
    expect(".modal").toHaveCount(0);
});

test("a popstate that does not move the page leaves popovers open", async () => {
    await makeMockEnv();
    class Host extends Component {
        static props = ["*"];
        static template = xml`<div class="anchor">a</div>`;
    }
    await mountWithCleanup(Host);
    getService("popover").add(queryOne(".anchor"), Content, {});
    await animationFrame();
    expect(".o_popover").toHaveCount(1);

    // What router.pushEphemeral/releaseEphemeral produce: same URL, so the user
    // never left the page and the popover has no reason to collapse.
    window.dispatchEvent(new PopStateEvent("popstate", { state: null }));
    await animationFrame();
    expect(".o_popover").toHaveCount(1);
});

test("unblocking more than blocking does not broadcast a phantom unblock", async () => {
    await makeMockEnv();
    const ui = getService("ui");
    ui.bus.addEventListener("UNBLOCK", () => expect.step("UNBLOCK"));

    ui.unblock();
    expect.verifySteps([]);

    ui.block();
    ui.unblock();
    expect.verifySteps(["UNBLOCK"]);
});

test("the overlay presenter reads each option getter exactly once", async () => {
    // Options describe the moment of opening. makePopover takes care to hand
    // them over without spreading, but the presenter reads them here and gives
    // the overlay a plain snapshot -- so a caller writing `get class()` to
    // follow live state gets the value it had when the overlay was added, and
    // nothing after that.
    // Both mapping paths are covered: `class` is a shared option the presenter
    // maps itself, `position` reaches the props through the caller's toProps.
    let classReads = 0;
    let positionReads = 0;
    /** @type {any[]} */
    const added = [];
    const add = makeOverlayPresenter({
        overlay: {
            add(component, props) {
                added.push(props);
                return () => {};
            },
        },
        component: /** @type {any} */ (class {}),
        toProps: (options) => ({ position: options.position }),
    });
    add(
        /** @type {any} */ (document.body),
        /** @type {any} */ (class {}),
        {},
        {
            get class() {
                classReads++;
                return `cls-${classReads}`;
            },
            get position() {
                positionReads++;
                return `pos-${positionReads}`;
            },
        },
    );

    expect(classReads).toBe(1);
    expect(positionReads).toBe(1);
    expect(added[0].class).toBe("cls-1");
    expect(added[0].position).toBe("pos-1");
    expect(added[0].class).toBe("cls-1");
    expect(classReads).toBe(1);
    expect(positionReads).toBe(1);
});

// `usePopover({ useBottomSheet })` routes one call to either presenter, so a
// component hosted by them must get the same `close` either way. `web.Popover`
// hands over the presenter's own `close` untouched; `web.BottomSheet` has to
// intercept it to play the slide-out first, and used to drop the arguments on
// the floor — so the very callers that pass a result back through `close(...)`
// got `undefined` on exactly the breakpoints that produce a sheet.
class ClosingContent extends Component {
    static template = xml`<button class="closer" t-on-click="() => this.props.close({ answer: 42 })">x</button>`;
    static props = ["*"];
}

test.tags("mobile");
test("a bottom sheet forwards its hosted component's close parameters", async () => {
    mockTouch(true);
    await resize({ width: 375, height: 667 });
    await makeMockEnv();
    await mountWithCleanup(MainComponentsContainer);

    /** @type {any[]} */
    const seen = [];
    class Host extends Component {
        static template = xml`<div class="host"/>`;
        static props = ["*"];
        setup() {
            this.popover = usePopover(ClosingContent, {
                useBottomSheet: () => true,
                onClose: (params) => seen.push(params),
            });
        }
    }
    const host = await mountWithCleanup(Host);
    host.popover.open(queryOne(".host"), {});
    await animationFrame();
    await animationFrame();
    expect(".o_bottom_sheet").toHaveCount(1);

    queryOne(".closer").click();
    await runAllTimers();
    await animationFrame();
    expect(seen).toEqual([{ answer: 42 }]);
});

test("a popover forwards its hosted component's close parameters", async () => {
    await makeMockEnv();
    await mountWithCleanup(MainComponentsContainer);

    /** @type {any[]} */
    const seen = [];
    class Host extends Component {
        static template = xml`<div class="host"/>`;
        static props = ["*"];
        setup() {
            this.popover = usePopover(ClosingContent, {
                onClose: (params) => seen.push(params),
            });
        }
    }
    const host = await mountWithCleanup(Host);
    host.popover.open(queryOne(".host"), {});
    await animationFrame();

    queryOne(".closer").click();
    await runAllTimers();
    await animationFrame();
    expect(seen).toEqual([{ answer: 42 }]);
});

// `Popover` declared a `slots` prop its template never rendered, so slotted
// content vanished with no error. The prop is gone rather than implemented: the
// overlay presenter is the only thing that ever builds a Popover and it always
// passes `component`, so rendering a slot would only have traded a loud
// validation error for a silently empty popover.
test("a slotted popover is rejected rather than silently empty", async () => {
    await makeMockEnv();
    class SlotHost extends Component {
        static template = xml`<Popover target="target" close="() => {}" component="comp"><div class="slotted"/></Popover>`;
        static components = { Popover };
        static props = ["*"];
        setup() {
            this.target = document.body;
            this.comp = Content;
        }
    }
    let message = "none";
    onError((ev) => {
        message = String(ev.reason?.message ?? ev.reason);
        ev.preventDefault();
    });
    try {
        await mountWithCleanup(SlotHost);
        await animationFrame();
    } catch (e) {
        message = String(e?.message ?? e);
    }
    expect(message).toInclude("slots");
    expect(".slotted").toHaveCount(0);
});

// The presenters share one options object (`usePopover({ useBottomSheet })`
// picks between them at open time), so every option they both accept is mapped
// once, in the presenter. These pin the mappings that used to be duplicated per
// service and could drift apart.
test("both presenters honour the popoverClass alias and the class option", async () => {
    await makeMockEnv();
    await mountWithCleanup(MainComponentsContainer);
    class Host extends Component {
        static template = xml`<div class="anchor">a</div>`;
        static props = ["*"];
    }
    await mountWithCleanup(Host);
    const anchor = queryOne(".anchor");

    const closePopover = getService("popover").add(
        anchor,
        Content,
        {},
        {
            popoverClass: "via-alias",
        },
    );
    await animationFrame();
    expect(".o_popover.via-alias").toHaveCount(1);
    closePopover();
    await animationFrame();

    getService("popover").add(anchor, Content, {}, { class: "via-class" });
    await animationFrame();
    expect(".o_popover.via-class").toHaveCount(1);
});

// A default that lived in `popover_service` reached only popovers opened
// through the service, so a <Popover> written in a template trapped no focus
// while the <BottomSheet> it is interchangeable with did.
// `useActiveElement` deliberately declines to claim a region nothing inside can
// be focused, so both of these need focusable content to mean anything.
class FocusableContent extends Component {
    static template = xml`<div class="popover-content"><button class="in">i</button></div>`;
    static props = ["*"];
}

test("a <Popover> written in a template claims the UI like a sheet does", async () => {
    await makeMockEnv();
    class DirectHost extends Component {
        static template = xml`<Popover target="t" close="() => {}" component="c"/>`;
        static components = { Popover };
        static props = ["*"];
        setup() {
            this.t = document.body;
            this.c = FocusableContent;
        }
    }
    await mountWithCleanup(DirectHost);
    await animationFrame();
    await animationFrame();
    expect(getService("ui").activeElement).not.toBe(document);
});

test("Dropdown can still opt out of claiming the UI", async () => {
    await makeMockEnv();
    await mountWithCleanup(MainComponentsContainer);
    class Host extends Component {
        static template = xml`<div class="anchor">a</div>`;
        static props = ["*"];
    }
    await mountWithCleanup(Host);
    const anchor = queryOne(".anchor");

    // Same content, so the only difference is the option under test.
    const close = getService("popover").add(anchor, FocusableContent, {}, {});
    await animationFrame();
    await animationFrame();
    expect(getService("ui").activeElement).not.toBe(document);
    close();
    await animationFrame();

    getService("popover").add(
        anchor,
        FocusableContent,
        {},
        {
            setActiveElement: false,
        },
    );
    await animationFrame();
    await animationFrame();
    expect(getService("ui").activeElement).toBe(document);
});

// Removal awaits the caller's onClose, so the hook's close() is the only handle
// on "the popover is actually gone". It discarded the promise.
test("the popover hook hands back an awaitable close", async () => {
    await makeMockEnv();
    await mountWithCleanup(MainComponentsContainer);
    /** @type {string[]} */
    const order = [];
    let release = () => {};
    const slow = new Promise((resolve) => {
        release = () => resolve(undefined);
    });
    class Host extends Component {
        static template = xml`<div class="anchor">a</div>`;
        static props = ["*"];
        setup() {
            this.popover = usePopover(Content, {
                onClose: async () => {
                    await slow;
                    order.push("onClose");
                },
            });
        }
    }
    const host = await mountWithCleanup(Host);
    host.popover.open(queryOne(".anchor"), {});
    await animationFrame();

    const closed = host.popover.close().then(() => order.push("awaited"));
    release();
    await closed;
    expect(order).toEqual(["onClose", "awaited"]);
});

// A target watched while still detached had its observer bound to the orphan
// subtree, which nothing mutates again -- so the removal that mattered, once it
// was in the page, never reached the watcher.
test("a target watched before it is attached still reports its removal", async () => {
    const orphan = document.createElement("div");
    let detached = 0;
    const unwatch = watchForDetachedTarget(orphan, () => detached++);

    document.body.appendChild(orphan);
    await animationFrame();
    expect(detached).toBe(0);

    orphan.remove();
    await animationFrame();
    expect(detached).toBe(1);
    unwatch();
});
