import { registry } from "@web/core/registry";

const BLOOD = ".o_partner_network_legend_item:has(.o_partner_network_category_blood)";

function nodeCount() {
    return document.querySelectorAll(".o_partner_network_node").length;
}

function checkedKinds() {
    return document.querySelectorAll(".o_partner_network_legend_item input:checked")
        .length;
}

function relatedShown() {
    return Number(
        document
            .querySelector(".o_partner_network_toolbar .text-muted")
            .parentElement.textContent.match(/(\d+) related/)[1],
    );
}

// Every contact on screen is counted once, by the tie that reached it, so the
// filter counts must always add up to the figure beside them. Checked after
// every toggle and not only at load: an earlier version was right on arrival
// and then froze, so hiding a kind moved the header from 20 to 16 while every
// count stood still.
function assertCountsAddUp(where) {
    const counts = [...document.querySelectorAll(".o_partner_network_count")].reduce(
        (sum, node) => sum + Number(node.textContent.trim()),
        0,
    );
    const related = relatedShown();
    if (counts !== related) {
        throw new Error(`${where}: counts sum to ${counts}, header says ${related}`);
    }
}

// The widget only ever renders inside a form view, and every defect it has had
// so far -- a paper that drew nothing, a palette that resolved to black, a
// canvas that collapsed to zero height -- was invisible to a unit test of the
// layout and obvious the moment something drew it. So this walks the real
// thing: what it draws, the size it draws at, and the filters over it.
registry.category("web_tour.tours").add("partner_network_tour", {
    url: "/odoo/action-partner_relationship.action_res_partner_network",
    steps: () => [
        {
            content: "open the seeded contact",
            trigger: ".o_list_view td:contains(Juan Ramirez Solis)",
            run: "click",
        },
        {
            content: "the diagram drew at least one node",
            trigger: ".o_partner_network_canvas .o_partner_network_node",
        },
        {
            content: "the focus is marked",
            trigger: ".o_partner_network_canvas .o_partner_network_focus",
        },
        {
            content: "every category the payload named has a filter",
            trigger: ".o_partner_network_legend .o_partner_network_legend_item",
            run() {
                const kinds = document.querySelectorAll(
                    ".o_partner_network_legend_item",
                ).length;
                if (kinds !== 6) {
                    throw new Error(`${kinds} filters, expected 6`);
                }
                if (checkedKinds() !== 6) {
                    throw new Error("not every kind starts checked");
                }
                assertCountsAddUp("on arrival");
            },
        },
        {
            content: "a category swatch carries a real colour, not the initial value",
            trigger: ".o_partner_network_swatch.o_partner_network_category_blood",
            run() {
                const swatch = document.querySelector(
                    ".o_partner_network_swatch.o_partner_network_category_blood",
                );
                const colour = getComputedStyle(swatch).backgroundColor;
                if (
                    !colour ||
                    colour === "rgba(0, 0, 0, 0)" ||
                    colour === "rgb(0, 0, 0)"
                ) {
                    throw new Error(`blood swatch resolved to ${colour}`);
                }
                const link = document.querySelector(
                    ".o_partner_network_category_blood",
                );
                if (getComputedStyle(link).stroke === "none") {
                    throw new Error("blood link stroke resolved to none");
                }
            },
        },
        {
            content: "the zoom controls are present",
            trigger: ".o_partner_network_toolbar .fa-search-plus",
        },
        {
            content: "the diagram can be recentred",
            trigger: ".o_partner_network_toolbar .fa-crosshairs",
        },
        {
            // Presence is not enough. JointJS writes its size inline on the
            // element it is handed, so a box that collapses to zero height
            // still holds every node in the DOM and every selector above still
            // matches -- the diagram is simply invisible, and the fit clamps to
            // the minimum scale. Measure the box and the drawn extent instead.
            content: "the diagram has real size on screen",
            trigger: ".o_partner_network_canvas",
            run() {
                const box = this.anchor.getBoundingClientRect();
                if (box.height < 200) {
                    throw new Error(`canvas collapsed to ${box.height}px tall`);
                }
                const drawn = document
                    .querySelector(".o_partner_network_canvas svg")
                    .getBoundingClientRect();
                if (drawn.height < 100 || drawn.width < 100) {
                    throw new Error(`paper drew ${drawn.width}x${drawn.height}`);
                }
                const zoom = document
                    .querySelector(".o_partner_network_zoom")
                    .textContent.trim();
                if (zoom === "20%") {
                    throw new Error("fit clamped to the minimum scale");
                }
                // The full-page action must use the room it has and no more.
                // A JointJS paper reports scrollWidth === clientWidth, so a box
                // taller than the window is not scrolled to -- it is cut off,
                // silently. This ran 147px past the fold before the box was
                // sized from its own offset rather than from a guess at the
                // chrome above it.
                if (this.anchor.closest(".o_partner_network_full")) {
                    // Across, too. A form sheet caps at 1400px so prose stays
                    // readable, and on a record with a chatter the rest is the
                    // chatter's -- this form has none, so past that width the
                    // remainder was simply blank: 520px of it at 1920, with the
                    // diagram squeezed into the left two thirds.
                    const content = document
                        .querySelector(".o_content")
                        .getBoundingClientRect();
                    if (box.width < content.width * 0.9) {
                        throw new Error(
                            `canvas is ${Math.round(box.width)}px wide in ${Math.round(content.width)}px of window`,
                        );
                    }
                    const slack = window.innerHeight - box.bottom;
                    if (slack < 0) {
                        throw new Error(
                            `canvas overruns the window by ${-Math.round(slack)}px`,
                        );
                    }
                    if (slack > 120) {
                        throw new Error(
                            `canvas leaves ${Math.round(slack)}px of the window unused`,
                        );
                    }
                }
                window.__networkNodesBefore = nodeCount();
            },
        },
        {
            // Measured on the RENDERED boxes, not on the layout's model of
            // them. The model reported zero collisions while four labels were
            // visibly sitting on nodes: it placed them along the centre-to-
            // centre line while JointJS draws the link boundary to boundary,
            // and nothing but the DOM could tell the two apart.
            content: "no edge label sits on a contact",
            trigger: ".o_partner_network_canvas svg",
            run() {
                const svg = this.anchor;
                const nodes = [...svg.querySelectorAll(".o_partner_network_node")].map(
                    (el) => el.getBoundingClientRect(),
                );
                const labels = [
                    ...svg.querySelectorAll(".o_partner_network_edge_label"),
                ];
                const over = (a, b) =>
                    a.left < b.right &&
                    b.left < a.right &&
                    a.top < b.bottom &&
                    b.top < a.bottom;
                const sitting = labels
                    .filter((el) =>
                        nodes.some((node) => over(el.getBoundingClientRect(), node)),
                    )
                    .map((el) => el.textContent);
                if (sitting.length) {
                    throw new Error(
                        `${sitting.length} of ${labels.length} labels sit on a contact: ${sitting.join(", ")}`,
                    );
                }
                if (!labels.length || !nodes.length) {
                    throw new Error("nothing drawn to check");
                }
            },
        },
        {
            content: "hide the blood ties",
            trigger: `${BLOOD} input`,
            run: "click",
        },
        {
            content: "hiding a kind redraws with fewer contacts",
            trigger: ".o_partner_network_legend_off",
            run() {
                if (!(nodeCount() < window.__networkNodesBefore)) {
                    throw new Error(
                        `hiding blood left ${nodeCount()} nodes, was ${window.__networkNodesBefore}`,
                    );
                }
                if (checkedKinds() !== 5) {
                    throw new Error(`${checkedKinds()} kinds checked, expected 5`);
                }
                assertCountsAddUp("after hiding a kind");
            },
        },
        {
            content: "restore the blood ties",
            trigger: `${BLOOD} input`,
            run: "click",
        },
        {
            content: "the contacts come back",
            trigger: `${BLOOD}:not(.o_partner_network_legend_off)`,
            run() {
                if (nodeCount() !== window.__networkNodesBefore) {
                    throw new Error(
                        `restoring blood gave ${nodeCount()} nodes, expected ${window.__networkNodesBefore}`,
                    );
                }
            },
        },
        {
            content: "with everything checked, All has nothing to do",
            trigger: ".o_partner_network_legend .btn:contains(All)[disabled]",
        },
        {
            content: "clear every kind at once",
            trigger: ".o_partner_network_legend .btn:contains(None)",
            run: "click",
        },
        {
            // Trigger-only on purpose: a step carrying a run() waits for its
            // trigger to become actionable, and a disabled button never does,
            // so asserting the disabled state AND reading the DOM in one step
            // hangs until the tour times out. Assert here, measure below.
            content: "clearing disables None",
            trigger: ".o_partner_network_legend .btn:contains(None)[disabled]",
        },
        {
            content: "clearing leaves nothing checked",
            trigger: ".o_partner_network_legend",
            run() {
                if (checkedKinds() !== 0) {
                    throw new Error(`${checkedKinds()} kinds still checked after None`);
                }
            },
        },
        {
            content: "bring them all back",
            trigger: ".o_partner_network_legend .btn:contains(All)",
            run: "click",
        },
        {
            content: "restoring every kind restores every contact",
            trigger: ".o_partner_network_canvas .o_partner_network_node",
            run() {
                if (nodeCount() !== window.__networkNodesBefore) {
                    throw new Error(
                        `All gave ${nodeCount()} nodes, expected ${window.__networkNodesBefore}`,
                    );
                }
                assertCountsAddUp("after All");
            },
        },
        {
            content: "isolate a single kind",
            trigger: `${BLOOD} .o_partner_network_only`,
            run: "click",
        },
        {
            content: "only that kind is left checked",
            trigger: ".o_partner_network_legend_off",
            run() {
                if (checkedKinds() !== 1) {
                    throw new Error(`only left ${checkedKinds()} kinds checked`);
                }
                assertCountsAddUp("after only");
                if (!(nodeCount() < window.__networkNodesBefore)) {
                    throw new Error(`only left ${nodeCount()} nodes, expected fewer`);
                }
            },
        },
    ],
});
