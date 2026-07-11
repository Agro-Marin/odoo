// @ts-check

import { after, expect, getFixture, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { renderToString } from "@web/core/utils/render";
import publicWidget from "@web/legacy/js/public/public_widget";

// Hoot port of the former QUnit suite `tests/legacy/public/public_widget_tests.js`.
// `publicWidget.Widget` (src/legacy/js/public/public_widget.js) is still
// production code, shipped in `web.assets_frontend`.

const Widget = publicWidget.Widget;

/** @param {InstanceType<Widget>} widget */
function useWidget(widget) {
    after(() => widget.destroy());
    return widget;
}

/** @param {EventTarget} el */
function click(el) {
    el.dispatchEvent(
        new MouseEvent("click", { bubbles: true, cancelable: true, view: window }),
    );
}

test("proxy (String)", () => {
    const W = Widget.extend({
        exec() {
            this.executed = true;
        },
    });
    const w = useWidget(new W());
    const fn = w.proxy("exec");
    fn();
    expect(w.executed).toBe(true, {
        message: "should execute the named method in the right context",
    });
});

test("proxy (String)(*args)", () => {
    const W = Widget.extend({
        exec(arg) {
            this.executed = arg;
        },
    });
    const w = useWidget(new W());
    const fn = w.proxy("exec");
    fn(42);
    expect(w.executed).toBe(42, { message: "should be passed the proxy's arguments" });
});

test("proxy (String), include", () => {
    // the proxy function should handle methods being changed on the class
    // and should always proxy "by name", to the most recent one
    const W = Widget.extend({
        exec() {
            this.executed = 1;
        },
    });
    const w = useWidget(new W());
    const fn = w.proxy("exec");
    W.include({
        exec() {
            this.executed = 2;
        },
    });
    fn();
    expect(w.executed).toBe(2, { message: "should be lazily resolved" });
});

test("proxy (Function)", () => {
    const w = useWidget(new (Widget.extend({}))());
    const fn = w.proxy(function () {
        this.executed = true;
    });
    fn();
    expect(w.executed).toBe(true, {
        message: "should set the function's context (like Function#bind)",
    });
});

test("proxy (Function)(*args)", () => {
    const w = useWidget(new (Widget.extend({}))());
    const fn = w.proxy(function (arg) {
        this.executed = arg;
    });
    fn(42);
    expect(w.executed).toBe(42, { message: "should be passed the proxy's arguments" });
});

test("renderElement, no template, default", () => {
    const widget = useWidget(new (Widget.extend({}))());

    expect(widget.el).toBe(undefined, { message: "should not have a root element" });

    widget.renderElement();

    expect(widget.el).not.toBe(undefined, {
        message: "should have generated a root element",
    });
    expect(widget.$el).toBe(widget.el, { message: "should provide $el alias" });
    expect(widget.el.nodeName).toBe("DIV", {
        message: "should have generated the default element",
    });
    expect(widget.el.attributes.length).toBe(0, {
        message: "should not have generated any attribute",
    });
    expect(widget.el.innerHTML).toBe("", {
        message: "should not have generated any content",
    });
});

test("no template, custom tag", () => {
    const widget = useWidget(new (Widget.extend({ tagName: "ul" }))());
    widget.renderElement();
    expect(widget.el.nodeName).toBe("UL", {
        message: "should have generated the custom element tag",
    });
});

test("no template, @id", () => {
    const widget = useWidget(new (Widget.extend({ id: "foo" }))());
    widget.renderElement();

    expect(widget.el.attributes.length).toBe(1, {
        message: "should have one attribute",
    });
    expect(widget.el.getAttribute("id")).toBe("foo", {
        message: "should have generated the id attribute",
    });
    expect(widget.el.id).toBe("foo", {
        message: "should also be available via property",
    });
});

test("no template, @className", () => {
    const widget = useWidget(new (Widget.extend({ className: "oe_some_class" }))());
    widget.renderElement();

    expect(widget.el.className).toBe("oe_some_class", {
        message: "should have the right property",
    });
    expect(widget.el.getAttribute("class")).toBe("oe_some_class", {
        message: "should have the right attribute",
    });
});

test("no template, bunch of attributes", () => {
    const widget = useWidget(
        new (Widget.extend({
            attributes: {
                id: "some_id",
                class: "some_class",
                "data-foo": "data attribute",
                clark: "gable",
                spoiler: "snape kills dumbledore",
            },
        }))(),
    );
    widget.renderElement();

    expect(widget.el.attributes.length).toBe(5, {
        message: "should have all the specified attributes",
    });
    expect(widget.el.id).toBe("some_id");
    expect(widget.el.className).toBe("some_class");
    expect(widget.el.dataset.foo).toBe("data attribute");
    expect(widget.el.getAttribute("clark")).toBe("gable");
    expect(widget.el.getAttribute("spoiler")).toBe("snape kills dumbledore");
});

test("template", () => {
    renderToString.app.addTemplate(
        "test.public.widget.template.1",
        `<ol>
            <li t-foreach="[0, 1, 2, 3, 4]" t-as="counter" t-key="counter_index" t-attf-class="class-#{counter}">
                <input/>
                <t t-esc="counter"/>
            </li>
        </ol>`,
    );

    const widget = useWidget(
        new (Widget.extend({ template: "test.public.widget.template.1" }))(),
    );
    widget.renderElement();

    expect(widget.el.nodeName).toBe("OL");
    expect(widget.el.children.length).toBe(5);
    expect(widget.el.textContent).toBe("01234");
});

test("repeated rendering", async () => {
    const fixture = getFixture();
    renderToString.app.addTemplate(
        "test.public.widget.template.2",
        `<p><t t-esc="widget.value"/></p>`,
    );
    const widget = useWidget(
        new (Widget.extend({ template: "test.public.widget.template.2" }))(),
    );
    widget.value = 42;

    await widget.appendTo(fixture);
    expect(fixture.querySelector("p").textContent).toBe("42", {
        message: "DOM fixture should contain initial value",
    });
    expect(widget.el.textContent).toBe("42", { message: "should set initial value" });
    widget.value = 36;
    widget.renderElement();
    expect(fixture.querySelector("p").textContent).toBe("36", {
        message: "DOM fixture should use new value",
    });
    expect(widget.el.textContent).toBe("36", { message: "should set new value" });
});

test("event delegation", async () => {
    renderToString.app.addTemplate(
        "test.public.widget.template.3",
        `<ol>
            <li t-foreach="[0, 1, 2, 3, 4]" t-as="counter" t-key="counter_index" t-attf-class="class-#{counter}">
                <input/>
                <t t-esc="counter"/>
            </li>
        </ol>`,
    );

    const a = [];
    const widget = useWidget(
        new (Widget.extend({
            template: "test.public.widget.template.3",
            events: {
                click() {
                    a[0] = true;
                    expect(this).toBe(widget, {
                        message: "should trigger events in widget",
                    });
                },
                "click li.class-3": "class3",
                "change input"() {
                    a[2] = true;
                },
            },
            class3() {
                a[1] = true;
            },
        }))(),
    );
    widget.renderElement();

    click(widget.el);
    click(widget.el.querySelectorAll("li")[3]);
    const inputs = widget.el.querySelectorAll("input");
    const lastInput = inputs[inputs.length - 1];
    lastInput.value = "foo";
    lastInput.dispatchEvent(new Event("change", { bubbles: true }));

    for (let i = 0; i < 3; i++) {
        expect(a[i]).toBe(true, { message: `should pass test ${i}` });
    }
});

test("undelegate", async () => {
    renderToString.app.addTemplate(
        "test.public.widget.template.4",
        `<ol>
            <li t-foreach="[0, 1, 2, 3, 4]" t-as="counter" t-key="counter_index" t-attf-class="class-#{counter}">
                <input/>
                <t t-esc="counter"/>
            </li>
        </ol>`,
    );

    let clicked = false;
    let newclicked = false;

    const widget = useWidget(
        new (Widget.extend({
            template: "test.public.widget.template.4",
            events: {
                "click li"() {
                    clicked = true;
                },
            },
        }))(),
    );
    widget.renderElement();
    widget.el.addEventListener("click", (ev) => {
        if (ev.target.closest("li")) {
            newclicked = true;
        }
    });

    click(widget.el.querySelector("li"));
    expect(clicked).toBe(true, { message: "should trigger bound events" });
    expect(newclicked).toBe(true, { message: "should trigger bound events" });

    clicked = newclicked = false;
    widget._undelegateEvents();
    click(widget.el.querySelector("li"));
    expect(clicked).toBe(false, {
        message: "undelegate should unbind events delegated",
    });
    expect(newclicked).toBe(true, {
        message: "undelegate should only unbind events it created",
    });
});

test("delegated handler does not leak currentTarget to later listeners", async () => {
    const fixture = getFixture();
    renderToString.app.addTemplate(
        "test.public.widget.template.5",
        `<ol>
            <li t-foreach="[0, 1, 2]" t-as="counter" t-key="counter_index" t-attf-class="class-#{counter}">
                <t t-esc="counter"/>
            </li>
        </ol>`,
    );

    let capturedEvent = null;
    const widget = useWidget(
        new (Widget.extend({
            template: "test.public.widget.template.5",
            events: {
                "click li": "onLiClick",
            },
            onLiClick(ev) {
                capturedEvent = ev;
                expect.step("delegated");
                expect(ev.currentTarget).toBe(this.el.querySelector("li.class-1"), {
                    message:
                        "delegated handler should see the delegate target as currentTarget",
                });
            },
        }))(),
    );
    widget.renderElement();
    fixture.appendChild(widget.el);
    fixture.addEventListener("click", function ancestorHandler(ev) {
        expect.step("ancestor");
        expect(ev.currentTarget).toBe(fixture, {
            message:
                "an ancestor plain handler running after the delegated one should see its own element",
        });
        fixture.removeEventListener("click", ancestorHandler);
    });

    click(widget.el.querySelector("li.class-1"));

    expect.verifySteps(["delegated", "ancestor"]);
    expect(Object.hasOwn(capturedEvent, "currentTarget")).toBe(false, {
        message: "the own currentTarget property must not survive the dispatch",
    });
});

test("start is not called when widget is destroyed", async () => {
    const fixture = getFixture();
    // Note: willStart is always async
    const MyWidget = Widget.extend({
        start() {
            expect.step("started");
        },
    });

    const widget = new MyWidget();
    widget.appendTo(fixture);
    widget.destroy();

    const divEl = document.createElement("div");
    fixture.appendChild(divEl);
    const widget2 = new MyWidget();
    widget2.attachTo(divEl);
    widget2.destroy();

    await animationFrame();
    expect.verifySteps([]);
});

test("don't destroy twice widget's children", () => {
    const parent = new Widget();
    new (Widget.extend({
        destroy() {
            expect.step("destroy");
        },
    }))(parent);

    parent.destroy();
    expect.verifySteps(["destroy"]);
});
