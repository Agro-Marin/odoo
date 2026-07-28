// @ts-check

import { afterEach, describe, expect, getFixture, test } from "@odoo/hoot";
import { animationFrame, runAllTimers } from "@odoo/hoot-mock";
import { getScrollingElement } from "@web/core/utils/dom/scrolling";
import {
    Alert,
    Button,
    Carousel,
    Collapse,
    Dropdown,
    Modal,
    Offcanvas,
    Popover,
    ScrollSpy,
    Tab,
    Toast,
    Tooltip,
} from "@web/libs/bootstrap";

describe.current.tags("headless");

afterEach(() => {
    document
        .querySelectorAll(".tooltip, .popover, .modal-backdrop")
        .forEach((el) => el.remove());
    document.querySelectorAll("body > .modal").forEach((el) => el.remove());
    document.body.classList.remove("modal-open");
    document.body.style.overflow = "";
    document.body.style.paddingRight = "";
});

function mount(html) {
    const fixture = getFixture();
    fixture.innerHTML = html;
    return fixture.firstElementChild;
}

const MODAL_HTML = `<div class="modal"><div class="modal-dialog"><div class="modal-content">m</div></div></div>`;

/** A second document, to exercise the cross-document paths. */
async function scrollingIframe(bodyInner = "") {
    const iframe = document.createElement("iframe");
    iframe.style.cssText = "width:300px;height:200px;border:0";
    getFixture().appendChild(iframe);
    await new Promise((resolve) => {
        iframe.addEventListener("load", resolve, { once: true });
        iframe.srcdoc =
            `<body style="margin:0;height:200px;overflow:hidden">` +
            `<div id="wrap" style="height:200px;overflow-y:auto"><div style="height:3000px"></div></div>` +
            bodyInner +
            `</body>`;
    });
    return iframe;
}

function tipCount() {
    return document.querySelectorAll(".tooltip").length;
}

describe("sanitizer allow list", () => {
    test("strips inline style and data-bs-* but keeps plain data-*", async () => {
        const el = mount(`<button>x</button>`);
        const tt = new Tooltip(el, {
            title: `<b style="position:fixed;width:100vw" data-bs-toggle="modal" data-foo="1" onclick="x">hi</b>`,
            animation: false,
        });
        tt.show();
        await animationFrame();
        expect(document.querySelector(".tooltip-inner")?.innerHTML).toBe(
            `<b data-foo="1">hi</b>`,
        );
        tt.dispose();
    });

    test("data-bs prefix is rejected but data-bsomething is not", async () => {
        const pattern = Tooltip.Default.allowList["*"].at(-1);
        expect(pattern.test("data-bs-toggle")).toBe(false);
        expect(pattern.test("data-bsomething")).toBe(true);
        expect(pattern.test("data-foo")).toBe(true);
        expect(pattern.test("datax-foo")).toBe(false);
    });

    test("data-tooltip is rejected, since Odoo's own data-api acts on it", async () => {
        const pattern = Tooltip.Default.allowList["*"].at(-1);
        for (const attr of [
            "data-tooltip",
            "data-tooltip-template",
            "data-tooltip-info",
            "data-tooltip-position",
            "data-tooltip-delay",
        ]) {
            expect(pattern.test(attr)).toBe(false);
        }
        // only the API's own prefix, not anything merely starting with it
        expect(pattern.test("data-tooltipfoo")).toBe(true);
    });

    // The tooltip service delegates from body in the capture phase and opens on
    // any [data-tooltip], [data-tooltip-template] it sees, and a tip is appended
    // to body. `web.Tooltip` then renders t-call="{{props.template}}" with
    // t-call-context="{ env, ...props.info }", so a surviving pair would let a
    // stored record choose which internal template renders, and with what
    // context. Server-side html_sanitize keeps every data-*, so this list is
    // the only thing in the way.
    test("stored content cannot drive Odoo's tooltip service", async () => {
        const root = mount(`<div><span id="a">hover</span></div>`);
        const tt = new Tooltip(root.querySelector("#a"), {
            title:
                `<b data-tooltip="INJECTED" data-tooltip-template="web.Dialog.header"` +
                ` data-tooltip-info='{"x":1}'>x</b>`,
            animation: false,
        });
        tt.show();
        await animationFrame();
        const injected = document.querySelector(".tooltip-inner b");
        expect(injected).not.toBe(null);
        expect(injected.getAttribute("data-tooltip")).toBe(null);
        expect(injected.getAttribute("data-tooltip-template")).toBe(null);
        expect(injected.getAttribute("data-tooltip-info")).toBe(null);
        tt.dispose();
    });

    test("stored content cannot paint a viewport overlay", async () => {
        // verbatim output of Odoo's server-side html_sanitize() for a crafted
        // record, fed through website_forum's [data-bs-toggle=tooltip] sweep
        const root = mount(
            `<div><span data-bs-toggle="tooltip" title='&lt;b style="position:fixed;top:0;left:0;width:100vw;height:100vh"&gt;OVERLAY&lt;/b&gt;'>hover</span></div>`,
        );
        const anchor = root.querySelector("[data-bs-toggle='tooltip']");
        const tt = Tooltip.getOrCreateInstance(anchor, { animation: false });
        tt.show();
        await animationFrame();
        const injected = document.querySelector(".tooltip-inner b");
        expect(injected).not.toBe(null);
        expect(getComputedStyle(injected).position).not.toBe("fixed");
        expect(injected.getBoundingClientRect().width).toBeLessThan(window.innerWidth);
        tt.dispose();
    });

    test("tfoot is allow-listed (upstream allow-listed a non-existent tag)", async () => {
        expect("tfoot" in Tooltip.Default.allowList).toBe(true);
        expect("tfooter" in Tooltip.Default.allowList).toBe(false);
    });
});

describe("tooltip defaults", () => {
    test("uses the plural fallbackPlacements key Bootstrap reads", async () => {
        expect(Tooltip.Default.fallbackPlacements).toEqual([
            "bottom",
            "right",
            "left",
            "top",
        ]);
        expect("fallbackPlacement" in Tooltip.Default).toBe(false);
    });

    test("boundary is a value Popper understands", async () => {
        expect(Tooltip.Default.boundary).toBe("viewport");
    });

    // `Popover.Default` spreads `Tooltip.Default` when the bundle loads, before
    // this module runs, so it snapshots the scalars and shares only the
    // allowList reference. Call sites depend on both halves: website_forum
    // passes `html: true` explicitly because popovers do not inherit it.
    test("the tooltip defaults do not reach Popover, but the allow list does", async () => {
        expect(Popover.Default.allowList).toBe(Tooltip.Default.allowList);
        expect(Popover.Default.html).toBe(false);
        expect(Popover.Default.container).toBe(false);
        expect(Popover.Default.boundary).toBe("clippingParents");
        expect(Popover.Default.delay).toBe(0);
        expect(Tooltip.Default.html).toBe(true);
    });

    // The iframe fix keys on `document.body`; a popover reaches that value
    // through Bootstrap resolving `container: false`, not through the default.
    test("a popover anchored in an iframe is appended to that iframe", async () => {
        const iframe = await scrollingIframe(`<button id="p">P</button>`);
        const idoc = iframe.contentDocument;
        const po = new Popover(idoc.querySelector("#p"), {
            content: "P",
            animation: false,
        });
        po.show();
        await animationFrame();
        expect(idoc.querySelectorAll(".popover")).toHaveLength(1);
        expect(document.querySelectorAll(".popover")).toHaveLength(0);
        po.dispose();
        iframe.remove();
    });
});

describe("Tooltip.show", () => {
    test("only one tooltip is on screen at a time", async () => {
        const root = mount(
            `<div><button id="a">A</button><button id="b">B</button></div>`,
        );
        const ttA = new Tooltip(root.querySelector("#a"), {
            title: "A",
            animation: false,
        });
        const ttB = new Tooltip(root.querySelector("#b"), {
            title: "B",
            animation: false,
        });
        ttA.show();
        await animationFrame();
        expect(tipCount()).toBe(1);
        ttB.show();
        await animationFrame();
        expect(tipCount()).toBe(1);
        expect(document.querySelector(".tooltip-inner").textContent).toBe("B");
        ttA.dispose();
        ttB.dispose();
    });

    test("dismissing releases the popper and the aria-describedby", async () => {
        const root = mount(
            `<div><button id="a">A</button><button id="b">B</button></div>`,
        );
        const btnA = root.querySelector("#a");
        const ttA = new Tooltip(btnA, { title: "A", animation: false });
        const ttB = new Tooltip(root.querySelector("#b"), {
            title: "B",
            animation: false,
        });
        ttA.show();
        await animationFrame();
        expect(btnA.getAttribute("aria-describedby")).toMatch(/^tooltip/);
        ttB.show();
        await animationFrame();
        expect(ttA._popper).toBe(null);
        expect(ttA.tip).toBe(null);
        expect(btnA.getAttribute("aria-describedby")).toBe(null);
        ttA.dispose();
        ttB.dispose();
    });

    test("an orphaned tip is cleaned up when the next tooltip shows", async () => {
        const root = mount(
            `<div><button id="a">A</button><button id="b">B</button></div>`,
        );
        const btnA = root.querySelector("#a");
        const ttA = new Tooltip(btnA, { title: "A", animation: false });
        const ttB = new Tooltip(root.querySelector("#b"), {
            title: "B",
            animation: false,
        });
        ttA.show();
        await animationFrame();
        btnA.remove();
        expect(tipCount()).toBe(1);
        ttB.show();
        await animationFrame();
        expect(tipCount()).toBe(1);
        expect(ttA._popper).toBe(null);
        ttA.dispose();
        ttB.dispose();
    });

    test("a hidden anchor is skipped instead of throwing", async () => {
        const el = mount(`<button style="display:none">x</button>`);
        const tt = new Tooltip(el, { title: "X", animation: false });
        expect(() => tt.show()).not.toThrow();
        await animationFrame();
        expect(tipCount()).toBe(0);
        tt.dispose();
    });

    test("hover A then B then A still shows each tooltip", async () => {
        const root = mount(
            `<div><button id="a">A</button><button id="b">B</button></div>`,
        );
        const ttA = new Tooltip(root.querySelector("#a"), {
            title: "A",
            animation: false,
            delay: 0,
        });
        const ttB = new Tooltip(root.querySelector("#b"), {
            title: "B",
            animation: false,
            delay: 0,
        });
        const shown = [];
        for (const [enter, leave] of [
            [ttA, ttB],
            [ttB, ttA],
            [ttA, ttB],
        ]) {
            leave._leave();
            enter._enter();
            await runAllTimers();
            await animationFrame();
            shown.push(document.querySelector(".tooltip-inner")?.textContent ?? null);
        }
        expect(shown).toEqual(["A", "B", "A"]);
        ttA.dispose();
        ttB.dispose();
    });

    test("a popover neither becomes nor dismisses the tracked tooltip", async () => {
        const root = mount(
            `<div><button id="a">A</button><button id="p">P</button></div>`,
        );
        const ttA = new Tooltip(root.querySelector("#a"), {
            title: "A",
            animation: false,
        });
        const po = new Popover(root.querySelector("#p"), {
            content: "P",
            animation: false,
        });
        ttA.show();
        await animationFrame();
        po.show();
        await animationFrame();
        expect(document.querySelectorAll(".tooltip:not(.popover)")).toHaveLength(1);
        expect(document.querySelectorAll(".popover")).toHaveLength(1);
        ttA.dispose();
        po.dispose();
    });

    test("a tooltip anchored in an iframe is appended to that iframe", async () => {
        const iframe = await scrollingIframe(`<button id="a">A</button>`);
        const idoc = iframe.contentDocument;
        const tt = new Tooltip(idoc.querySelector("#a"), {
            title: "A",
            animation: false,
        });
        tt.show();
        await animationFrame();
        expect(idoc.querySelectorAll(".tooltip")).toHaveLength(1);
        expect(document.querySelectorAll(".tooltip")).toHaveLength(0);
        tt.dispose();
        iframe.remove();
    });

    test("an explicit container still wins over the anchor's document", async () => {
        const host = mount(`<div id="host"></div>`);
        const iframe = await scrollingIframe(`<button id="a">A</button>`);
        const idoc = iframe.contentDocument;
        const tt = new Tooltip(idoc.querySelector("#a"), {
            title: "A",
            animation: false,
            container: host,
        });
        tt.show();
        await animationFrame();
        expect(host.querySelectorAll(".tooltip")).toHaveLength(1);
        tt.dispose();
        iframe.remove();
    });

    test("a popover shown first is untouched by a later tooltip", async () => {
        const root = mount(
            `<div><button id="a">A</button><button id="p">P</button></div>`,
        );
        const ttA = new Tooltip(root.querySelector("#a"), {
            title: "A",
            animation: false,
        });
        const po = new Popover(root.querySelector("#p"), {
            content: "P",
            animation: false,
        });
        po.show();
        await animationFrame();
        ttA.show();
        await animationFrame();
        expect(tipCount()).toBe(1);
        expect(document.querySelectorAll(".popover")).toHaveLength(1);
        ttA.dispose();
        po.dispose();
    });

    test("a show() that renders nothing leaves the visible tooltip alone", async () => {
        const root = mount(
            `<div><button id="a">A</button><button id="b">B</button></div>`,
        );
        const ttA = new Tooltip(root.querySelector("#a"), {
            title: "A",
            animation: false,
        });
        // an empty title makes Bootstrap's show() give up before it inserts
        // anything, the same silent bail-out as a disabled instance or a
        // prevented show.bs.tooltip
        const ttB = new Tooltip(root.querySelector("#b"), {
            title: "",
            animation: false,
        });
        ttA.show();
        await animationFrame();
        ttB.show();
        await animationFrame();
        expect(tipCount()).toBe(1);
        expect(document.querySelector(".tooltip-inner").textContent).toBe("A");
        ttA.dispose();
        ttB.dispose();
    });

    test("a hidden anchor does not take the visible tooltip down with it", async () => {
        const root = mount(
            `<div><button id="a">A</button><button id="b" style="display:none">B</button></div>`,
        );
        const ttA = new Tooltip(root.querySelector("#a"), {
            title: "A",
            animation: false,
        });
        const ttB = new Tooltip(root.querySelector("#b"), {
            title: "B",
            animation: false,
        });
        ttA.show();
        await animationFrame();
        ttB.show();
        await animationFrame();
        expect(tipCount()).toBe(1);
        expect(document.querySelector(".tooltip-inner").textContent).toBe("A");
        ttA.dispose();
        ttB.dispose();
    });

    // Bootstrap keys instances in a strong Map that only dispose() clears, so an
    // anchor thrown away by a re-render keeps its element, its instance and its
    // listeners alive for the lifetime of the page.
    test("an anchor dropped by a re-render is not retained", async () => {
        const host = mount(`<div></div>`);
        const anchors = [];
        for (let i = 0; i < 10; i++) {
            host.innerHTML = `<button>x</button>`;
            const el = host.firstElementChild;
            const tt = Tooltip.getOrCreateInstance(el, {
                title: `t${i}`,
                animation: false,
            });
            tt.show();
            anchors.push(el);
            host.replaceChildren();
        }
        const live = mount(`<button>live</button>`);
        const ttLive = Tooltip.getOrCreateInstance(live, {
            title: "live",
            animation: false,
        });
        ttLive.show();
        await animationFrame();
        expect(anchors.filter((el) => Tooltip.getInstance(el))).toHaveLength(0);
        ttLive.dispose();
    });

    // Bootstrap's dispose nulls every own property, so a second call would
    // dereference a null `_element`. Call sites register unconditional
    // teardowns and cannot know whether a dismissal already disposed for them.
    test("dispose is idempotent", async () => {
        const el = mount(`<button>y</button>`);
        const tt = new Tooltip(el, { title: "Y", animation: false });
        tt.show();
        await animationFrame();
        tt.dispose();
        expect(() => tt.dispose()).not.toThrow();
    });

    test("a call-site teardown after a dismissal is safe", async () => {
        const host = mount(`<div><button>z</button></div>`);
        const el = host.firstElementChild;
        const tt = Tooltip.getOrCreateInstance(el, { title: "Z", animation: false });
        tt.show();
        await animationFrame();
        host.replaceChildren();
        const live = mount(`<button>live</button>`);
        const ttLive = new Tooltip(live, { title: "live", animation: false });
        ttLive.show();
        await animationFrame();
        expect(() => tt.dispose()).not.toThrow();
        ttLive.dispose();
    });

    test("disposing the tracked tooltip does not break the next show", async () => {
        const root = mount(
            `<div><button id="a">A</button><button id="b">B</button></div>`,
        );
        const ttA = new Tooltip(root.querySelector("#a"), {
            title: "A",
            animation: false,
        });
        const ttB = new Tooltip(root.querySelector("#b"), {
            title: "B",
            animation: false,
        });
        ttA.show();
        await animationFrame();
        ttA.dispose();
        expect(() => ttB.show()).not.toThrow();
        await animationFrame();
        expect(tipCount()).toBe(1);
        ttB.dispose();
    });
});

describe("Modal", () => {
    test("_adjustDialog has no page-level side effects", async () => {
        const el = mount(MODAL_HTML);
        const modal = new Modal(el);
        modal._adjustDialog();
        expect(document.body.style.overflow).toBe("");
        expect(document.body.classList.contains("modal-open")).toBe(false);
        modal.dispose();
    });

    test("_adjustDialog stays cheap enough for the resize handler", async () => {
        const el = mount(
            `<div class="modal show" style="display:block"><div class="modal-dialog"><div class="modal-content" style="height:2000px">m</div></div></div>`,
        );
        const modal = new Modal(el);
        for (let i = 0; i < 200; i++) {
            modal._adjustDialog();
        }
        const t0 = performance.now();
        for (let i = 0; i < 500; i++) {
            modal._adjustDialog();
        }
        const perCallUs = ((performance.now() - t0) / 500) * 1000;
        expect(perCallUs).toBeLessThan(30);
        modal.dispose();
    });

    // Pins the premise of dropping the upstream scrollbar-compensation patch:
    // it only ever acted when getScrollingElement() answered with a child of
    // body. Since 6454eb52086 the webclient scrolls the document instead, so
    // this is documentElement and Bootstrap's own ScrollBarHelper covers it.
    // If this ever fails, a layout grew a scrollable body child and the
    // compensation question is live again.
    test("the webclient scrolls the document, not a body child", async () => {
        const scrollable = getScrollingElement(document);
        expect(scrollable).toBe(document.documentElement);
        expect(document.body.contains(scrollable)).toBe(false);
    });

    test("show() leaves no inline padding on the scrolling element", async () => {
        const before = document.documentElement.getAttribute("style");
        const el = mount(MODAL_HTML);
        const modal = new Modal(el);
        modal.show();
        await animationFrame();
        modal.hide();
        await animationFrame();
        expect(document.documentElement.getAttribute("style")).toBe(before);
        modal.dispose();
    });

    // Characterises an unfixed Bootstrap defect, not a desired behaviour:
    // `_showElement` tests containment with `document.body.contains(...)` and
    // `Backdrop` resolves its `rootElement` with `getElement("body")`, both of
    // which mean the top-level document whatever document owns the modal. An
    // iframe-owned modal is therefore adopted out of the document that styles
    // and positions it. Fixing it means editing the vendored bundle - wrapping
    // cannot express it - so until then, do not open a Bootstrap Modal inside
    // the website editor's iframe. Flip these assertions when it is fixed.
    test("an iframe-owned modal is adopted into the top document (Bootstrap bug)", async () => {
        const iframe = await scrollingIframe(MODAL_HTML);
        const idoc = iframe.contentDocument;
        const modalEl = idoc.querySelector(".modal");
        const modal = new Modal(modalEl);
        modal.show();
        await animationFrame();
        expect(modalEl.ownerDocument).toBe(document);
        expect(idoc.body.contains(modalEl)).toBe(false);
        expect(idoc.querySelectorAll(".modal-backdrop")).toHaveLength(0);
        expect(document.querySelectorAll(".modal-backdrop")).toHaveLength(1);
        modal.dispose();
        iframe.remove();
    });
});

// The patches in `@web/libs/bootstrap` reach into Bootstrap internals that carry
// no compatibility promise. This suite is the upgrade tripwire: it fails on the
// bundle bump rather than silently in production.
describe("patched Bootstrap internals still exist", () => {
    test("the pinned version is the one the patches were written against", async () => {
        expect(Modal.VERSION).toBe("5.3.8");
    });

    test("the Tooltip hooks the patches build on are present", async () => {
        for (const name of [
            "show",
            "dispose",
            "_disposePopper",
            "_isShown",
            "_configAfterMerge",
        ]) {
            expect(typeof Tooltip.prototype[name]).toBe("function");
        }
        expect(Popover.prototype._configAfterMerge).toBe(
            Tooltip.prototype._configAfterMerge,
        );
        expect(Tooltip.Default.allowList["*"]).toBeInstanceOf(Array);
    });

    test("Modal is re-exported unpatched", async () => {
        expect(Object.hasOwn(Modal.prototype, "show")).toBe(true);
        for (const name of ["_resetAdjustments", "_adjustDialog"]) {
            expect(typeof Modal.prototype[name]).toBe("function");
        }
    });

    test("every Bootstrap component the bundle defines is re-exported", async () => {
        for (const component of [
            Alert,
            Button,
            Carousel,
            Collapse,
            Dropdown,
            Modal,
            Offcanvas,
            Popover,
            ScrollSpy,
            Tab,
            Toast,
            Tooltip,
        ]) {
            expect(typeof component).toBe("function");
            expect(typeof component.getOrCreateInstance).toBe("function");
        }
    });

    test("Dropdown still consults _detectNavbar", async () => {
        expect(typeof Dropdown.prototype._detectNavbar).toBe("function");
    });
});

describe("Dropdown", () => {
    // Characterises why call sites must not keep a toggle across a re-render:
    // the constructor resolves its menu with `findOne(menu, this._element
    // .parentNode)`, which throws on a null parent. Guarding belongs there, not
    // behind a fabricated stand-in instance in web.
    test("a toggle removed from the DOM is a hard error", async () => {
        expect(() =>
            Dropdown.getOrCreateInstance(document.createElement("button")),
        ).toThrow(/Illegal invocation/);
    });

    test("a toggle inside a detached subtree still works", async () => {
        const wrapper = document.createElement("div");
        wrapper.innerHTML = `<button data-bs-toggle="dropdown">t</button><ul class="dropdown-menu"><li><a class="dropdown-item" href="#">i</a></li></ul>`;
        const inst = Dropdown.getOrCreateInstance(wrapper.querySelector("button"));
        expect(inst).toBeInstanceOf(Dropdown);
        expect(() => inst.hide()).not.toThrow();
        inst.dispose();
    });

    test("the .dropdown wrapper resolves its menu through the parent fallback", async () => {
        const el = mount(
            `<div class="dropdown"><button class="dropdown-toggle" data-bs-toggle="dropdown">t</button><ul class="dropdown-menu"><li><a class="dropdown-item" href="#">i</a></li></ul></div>`,
        );
        const inst = Dropdown.getOrCreateInstance(el);
        expect(inst._menu).toHaveClass("dropdown-menu");
        inst.dispose();
    });

    test("a connected toggle still gets a real Dropdown", async () => {
        const el = mount(
            `<div><button data-bs-toggle="dropdown">t</button><ul class="dropdown-menu"><li><a class="dropdown-item" href="#">i</a></li></ul></div>`,
        );
        const inst = Dropdown.getOrCreateInstance(el.querySelector("button"));
        expect(inst).toBeInstanceOf(Dropdown);
        inst.dispose();
    });
});

describe("Font Awesome 4 shims", () => {
    // Every name declared in v4-shims.css, not a sample: these are the FA4 names
    // still hardcoded across ~178 files, and FA7 renders an undefined `--fa` as
    // nothing at all, so a missing shim is a silently blank icon.
    const LEGACY_NAMES = [
        "fa-arrow-circle-o-up",
        "fa-bell-o",
        "fa-building-o",
        "fa-calendar-check-o",
        "fa-calendar-o",
        "fa-calendar-plus-o",
        "fa-calendar-times-o",
        "fa-check-circle-o",
        "fa-check-square-o",
        "fa-circle-o-notch",
        "fa-circle-thin",
        "fa-clock-o",
        "fa-comment-o",
        "fa-commenting-o",
        "fa-comments-o",
        "fa-dot-circle-o",
        "fa-envelope-o",
        "fa-file-archive-o",
        "fa-file-audio-o",
        "fa-file-excel-o",
        "fa-file-image-o",
        "fa-file-o",
        "fa-file-pdf-o",
        "fa-file-powerpoint-o",
        "fa-file-text-o",
        "fa-file-video-o",
        "fa-file-word-o",
        "fa-files-o",
        "fa-flag-o",
        "fa-flash",
        "fa-folder-o",
        "fa-folder-open-o",
        "fa-hand-paper-o",
        "fa-handshake-o",
        "fa-hdd-o",
        "fa-heart-o",
        "fa-hourglass-o",
        "fa-id-card-o",
        "fa-life-bouy",
        "fa-lightbulb-o",
        "fa-map-o",
        "fa-money",
        "fa-newspaper-o",
        "fa-paper-plane-o",
        "fa-pencil-square-o",
        "fa-picture-o",
        "fa-question-circle-o",
        "fa-star-half-o",
        "fa-star-o",
        "fa-sun-o",
        "fa-trash-o",
        "fa-user-circle-o",
        "fa-user-o",
        "fa-youtube-play",
    ];

    test("every legacy icon name renders a real glyph", async () => {
        const fixture = getFixture();
        fixture.innerHTML = LEGACY_NAMES.map(
            (n) => `<i class="fa ${n}" id="${n}"></i>`,
        ).join("");
        const blank = [];
        for (const name of LEGACY_NAMES) {
            const el = fixture.querySelector(`#${name}`);
            const content = getComputedStyle(el, "::before").getPropertyValue(
                "content",
            );
            const glyph = getComputedStyle(el).getPropertyValue("--fa").trim();
            if (content === "none" || content === '""' || !glyph) {
                blank.push(`${name}(content=${content},--fa=${glyph || "unset"})`);
            }
        }
        expect(blank).toEqual([]);
    });

    test("the shim list covers every legacy name, with no stale extras", async () => {
        expect(LEGACY_NAMES.length).toBe(54);
        expect(new Set(LEGACY_NAMES).size).toBe(LEGACY_NAMES.length);
    });

    test("an -o shim renders the regular weight, beating a fa-solid base class", async () => {
        const el = mount(`<i class="fa-solid fa-star-o"></i>`);
        expect(getComputedStyle(el).fontWeight).toBe("400");
    });

    test("an unknown fa-* class still renders nothing", async () => {
        const el = mount(`<i class="fa fa-definitely-not-an-icon"></i>`);
        expect(getComputedStyle(el, "::before").getPropertyValue("content")).toBe(
            "none",
        );
    });
});
