// @ts-check

import { describe, expect, getFixture, test } from "@odoo/hoot";
import { HotkeyService } from "@web/core/hotkeys/hotkey_service";
import { Navigator } from "@web/core/navigation/navigation";
import { closestScrollableY } from "@web/core/utils/dom/scrolling";
import {
    attachShadowRoot,
    getActiveElement,
    getDeepActiveElement,
    getNextTabableElement,
    getPreviousTabableElement,
    getTabableElements,
    isVisible,
    viewOf,
} from "@web/core/utils/dom/ui";

describe.current.tags("headless");

/**
 * @param {string} html
 * @returns {ShadowRoot}
 */
function shadowFixture(html) {
    const host = document.createElement("div");
    getFixture().appendChild(host);
    const root = host.attachShadow({ mode: "open" });
    root.innerHTML = html;
    return root;
}

/**
 * @param {string} html
 * @returns {Document}
 */
function iframeFixture(html) {
    const iframe = document.createElement("iframe");
    getFixture().appendChild(iframe);
    const doc = /** @type {Document} */ (iframe.contentDocument);
    doc.body.innerHTML = html;
    return doc;
}

describe("getActiveElement", () => {
    test("answers in the node's own tree, not the top-level document", () => {
        const root = shadowFixture(`<button id="b">b</button>`);
        const b = /** @type {HTMLElement} */ (root.getElementById("b"));
        b.focus();

        expect(getActiveElement(b)).toBe(b);
        expect(getActiveElement(root)).toBe(b);
        expect(document.activeElement).toBe(root.host);
    });

    test("a nested shadow root is retargeted to its host, so contains() holds", () => {
        const outer = shadowFixture(`<div id="wrap"><div id="inner-host"></div></div>`);
        const innerHost = /** @type {HTMLElement} */ (
            outer.getElementById("inner-host")
        );
        const inner = innerHost.attachShadow({ mode: "open" });
        inner.innerHTML = `<button id="deep">deep</button>`;
        const deep = /** @type {HTMLElement} */ (inner.getElementById("deep"));
        deep.focus();

        const wrap = /** @type {HTMLElement} */ (outer.getElementById("wrap"));
        const active = /** @type {Node} */ (getActiveElement(wrap));
        expect(active).toBe(innerHost);
        expect(wrap.contains(active)).toBe(true);
        expect(getDeepActiveElement(wrap)).toBe(deep);
    });

    test("degrades to the document for a detached or absent node", () => {
        const detached = document.createElement("div");
        detached.innerHTML = `<button id="d">d</button>`;
        expect(getActiveElement(detached)).toBe(document.activeElement);
        expect(getActiveElement()).toBe(null);
        expect(viewOf(detached)).toBe(window);
    });

    test("returns null when nothing in the tree is focused", () => {
        const root = shadowFixture(`<button id="b">b</button>`);
        /** @type {HTMLElement} */ (document.activeElement)?.blur?.();
        expect(getActiveElement(root)).toBe(null);
    });
});

describe("tab order inside a shadow root", () => {
    test("getNextTabableElement steps forward from the focused element", () => {
        const root = shadowFixture(`
            <button id="b1">b1</button>
            <button id="b2">b2</button>
            <button id="b3">b3</button>
        `);
        /** @type {HTMLElement} */ (root.getElementById("b2")).focus();
        expect(getNextTabableElement(/** @type {any} */ (root))?.id).toBe("b3");
    });

    test("getPreviousTabableElement steps back from the focused element", () => {
        const root = shadowFixture(`
            <button id="b1">b1</button>
            <button id="b2">b2</button>
            <button id="b3">b3</button>
        `);
        /** @type {HTMLElement} */ (root.getElementById("b2")).focus();
        expect(getPreviousTabableElement(/** @type {any} */ (root))?.id).toBe("b1");
    });
});

describe("viewOf", () => {
    test("answers the element's own window, not the top-level one", () => {
        const doc = iframeFixture(`<div id="d">d</div>`);
        const d = /** @type {HTMLElement} */ (doc.getElementById("d"));
        expect(viewOf(d)).toBe(doc.defaultView);
        expect(viewOf(document.body)).toBe(window);
    });

    test("isVisible recognises a foreign Document", () => {
        const doc = iframeFixture("");
        expect(isVisible(doc)).toBe(true);
        expect(isVisible(/** @type {any} */ (doc.defaultView))).toBe(true);
    });
});

describe("Navigator inside a shadow root", () => {
    test("isFocused sees an item focused in the shadow tree", () => {
        const root = shadowFixture(
            `<div id="c"><button id="b1">b1</button><button id="b2">b2</button></div>`,
        );
        const container = /** @type {HTMLElement} */ (root.getElementById("c"));
        const nav = new Navigator(
            {
                getContainer: () => container,
                getItems: () => [...container.querySelectorAll("button")],
                shouldRegisterHotkeys: false,
            },
            /** @type {any} */ ({ add: () => () => {} }),
        );
        nav.update();
        /** @type {HTMLElement} */ (root.getElementById("b1")).focus();

        expect(nav.isFocused).toBe(true);
    });
});

describe("hotkey overlays outside the top-level document", () => {
    test("an overlay raised in a shadow root is taken back out", () => {
        const root = shadowFixture(
            `<div id="scope"><button data-hotkey="q" style="width:20px;height:20px">q</button></div>`,
        );
        const scope = /** @type {HTMLElement} */ (root.getElementById("scope"));
        const service = new HotkeyService({
            ui: { activeElement: scope, isBlocked: false },
        });

        service.addHotkeyOverlays(scope);
        expect(root.querySelectorAll(".o_web_hotkey_overlay")).toHaveLength(1);

        service.removeHotkeyOverlays();
        expect(root.querySelectorAll(".o_web_hotkey_overlay")).toHaveLength(0);

        service.destroy();
    });
});

describe("router click interception across a shadow boundary", () => {
    test("the composed path names the anchor that was actually clicked", () => {
        const fixture = getFixture();
        const outerAnchor = document.createElement("a");
        outerAnchor.href = "/odoo/outer";
        fixture.appendChild(outerAnchor);
        const host = document.createElement("div");
        outerAnchor.appendChild(host);
        const root = host.attachShadow({ mode: "open" });
        root.innerHTML = `<a id="inner" href="/odoo/inner">inner</a>`;

        /** @type {(string | undefined)[]} */
        const resolved = [];
        const onClick = (/** @type {any} */ ev) => {
            const target = /** @type {Element} */ (ev.composedPath?.()[0] ?? ev.target);
            resolved.push(target.closest?.("a")?.getAttribute("href"));
        };
        window.addEventListener("click", onClick);
        /** @type {HTMLElement} */ (root.getElementById("inner")).click();
        window.removeEventListener("click", onClick);

        expect(resolved).toEqual(["/odoo/inner"]);
    });
});

describe("scrolling across a shadow boundary", () => {
    test("closestScrollableY finds a scrollable outside the host", () => {
        const fixture = getFixture();
        const scroller = document.createElement("div");
        scroller.style.cssText = "overflow-y:auto;height:50px";
        fixture.appendChild(scroller);
        const host = document.createElement("div");
        scroller.appendChild(host);
        const root = host.attachShadow({ mode: "open" });
        root.innerHTML = `<div style="height:500px"><span id="leaf">x</span></div>`;
        scroller.insertAdjacentHTML("beforeend", `<div style="height:500px"></div>`);

        const leaf = /** @type {HTMLElement} */ (root.getElementById("leaf"));
        expect(closestScrollableY(leaf)).toBe(scroller);
        expect(closestScrollableY(host)).toBe(scroller);
    });

    test("it still stops at the top of a detached tree", () => {
        const detached = document.createElement("div");
        detached.innerHTML = `<span id="leaf">x</span>`;
        expect(closestScrollableY(detached.querySelector("#leaf"))).toBe(null);
    });
});

describe("tab order across a shadow boundary", () => {
    function hosted(/** @type {string} */ light, /** @type {string} */ shadow) {
        const wrap = document.createElement("div");
        getFixture().appendChild(wrap);
        wrap.innerHTML = light;
        const host = /** @type {HTMLElement} */ (wrap.querySelector("#host"));
        attachShadowRoot(host).innerHTML = shadow;
        return wrap;
    }

    test("the shadow tree contributes at the host's own position", () => {
        const wrap = hosted(
            `<button id="a">a</button><div id="host"></div><button id="z">z</button>`,
            `<button id="m1">m1</button><button id="m2">m2</button>`,
        );
        expect(getTabableElements(wrap).map((e) => e.id)).toEqual([
            "a",
            "m1",
            "m2",
            "z",
        ]);
    });

    test("a positive tabIndex still sorts ahead of 0 across the boundary", () => {
        const wrap = hosted(
            `<button id="zero">z</button><div id="host"></div>`,
            `<button id="one" tabindex="1">1</button>`,
        );
        expect(getTabableElements(wrap).map((e) => e.id)).toEqual(["one", "zero"]);
    });

    test("an inert host contributes nothing", () => {
        const wrap = hosted(
            `<button id="a">a</button><div inert=""><div id="host"></div></div>`,
            `<button id="m">m</button>`,
        );
        expect(getTabableElements(wrap).map((e) => e.id)).toEqual(["a"]);
    });

    test("a raw attachShadow stays invisible -- attach through the helper", () => {
        const wrap = document.createElement("div");
        getFixture().appendChild(wrap);
        wrap.innerHTML = `<button id="a">a</button><div id="host"></div>`;
        const host = /** @type {HTMLElement} */ (wrap.querySelector("#host"));
        host.attachShadow({ mode: "open" }).innerHTML = `<button id="m">m</button>`;
        expect(getTabableElements(wrap).map((e) => e.id)).toEqual(["a"]);
    });

    test("attachShadowRoot is idempotent", () => {
        const host = document.createElement("div");
        getFixture().appendChild(host);
        const first = attachShadowRoot(host);
        expect(attachShadowRoot(host)).toBe(first);
    });
});

describe("getDeepActiveElement descends both kinds of boundary", () => {
    test("through an iframe", async () => {
        const fixture = getFixture();
        const iframe = document.createElement("iframe");
        fixture.appendChild(iframe);
        await new Promise((resolve) => {
            iframe.addEventListener("load", resolve, { once: true });
            iframe.srcdoc = `<!doctype html><html><body><button id="deep">d</button></body></html>`;
        });
        const doc = /** @type {Document} */ (iframe.contentDocument);
        const deep = /** @type {HTMLElement} */ (doc.getElementById("deep"));
        deep.focus();

        expect(document.activeElement).toBe(iframe);
        expect(getDeepActiveElement(document)).toBe(deep);
    });

    test("through a shadow root inside an iframe", async () => {
        const fixture = getFixture();
        const iframe = document.createElement("iframe");
        fixture.appendChild(iframe);
        await new Promise((resolve) => {
            iframe.addEventListener("load", resolve, { once: true });
            iframe.srcdoc = `<!doctype html><html><body><div id="host"></div></body></html>`;
        });
        const doc = /** @type {Document} */ (iframe.contentDocument);
        const host = /** @type {HTMLElement} */ (doc.getElementById("host"));
        const root = host.attachShadow({ mode: "open" });
        root.innerHTML = `<button id="deep">d</button>`;
        const deep = /** @type {HTMLElement} */ (root.getElementById("deep"));
        deep.focus();

        expect(getDeepActiveElement(document)).toBe(deep);
    });

    test("it stops rather than looping when nothing is deeper", () => {
        const root = shadowFixture(`<button id="b">b</button>`);
        const b = /** @type {HTMLElement} */ (root.getElementById("b"));
        b.focus();
        expect(getDeepActiveElement(root)).toBe(b);
    });
});
