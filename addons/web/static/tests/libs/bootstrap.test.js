// @ts-check

import { afterEach, describe, expect, getFixture, test } from "@odoo/hoot";
import { animationFrame, runAllTimers } from "@odoo/hoot-mock";
import { Dropdown, Modal, Popover, Tooltip } from "@web/libs/bootstrap";

describe.current.tags("headless");

afterEach(() => {
    document.querySelectorAll(".tooltip, .popover").forEach((el) => el.remove());
    document.body.classList.remove("modal-open");
    document.body.style.overflow = "";
    document.body.style.paddingRight = "";
});

function mount(html) {
    const fixture = getFixture();
    fixture.innerHTML = html;
    return fixture.firstElementChild;
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

    test("a popover does not become the tracked tooltip", async () => {
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

describe("Modal scrollbar compensation", () => {
    test("_adjustDialog has no page-level side effects", async () => {
        const el = mount(
            `<div class="modal"><div class="modal-dialog"><div class="modal-content">m</div></div></div>`,
        );
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

    test("show() locks the modal's own document", async () => {
        const iframe = document.createElement("iframe");
        getFixture().appendChild(iframe);
        await new Promise((resolve) => {
            iframe.addEventListener("load", resolve, { once: true });
            iframe.srcdoc = `<body style="height:3000px"><div class="modal"><div class="modal-dialog"><div class="modal-content">m</div></div></div></body>`;
        });
        const idoc = iframe.contentDocument;
        const modal = new Modal(idoc.querySelector(".modal"));
        modal.show();
        await animationFrame();
        expect(modal._scrollBar._element).toBe(idoc.body);
        expect(document.body.style.overflow).toBe("");
        modal.dispose();
        iframe.remove();
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
    test("legacy icon names still render a glyph", async () => {
        const legacy = [
            "fa-circle-o-notch",
            "fa-pencil-square-o",
            "fa-star-o",
            "fa-file-text-o",
            "fa-trash-o",
            "fa-money",
            "fa-picture-o",
            "fa-youtube-play",
        ];
        const fixture = getFixture();
        fixture.innerHTML = legacy
            .map((n) => `<i class="fa ${n}" id="${n}"></i>`)
            .join("");
        for (const name of legacy) {
            const content = getComputedStyle(
                fixture.querySelector(`#${name}`),
                "::before",
            ).getPropertyValue("content");
            expect(content).not.toBe("none");
        }
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
