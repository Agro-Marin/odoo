import { afterEach, describe, expect, test } from "@odoo/hoot";
import { loadJoint } from "@partner_relationship/lib/joint";
import {
    CATEGORY_ORDER,
    edgeClass,
    filterNetwork,
    labelAnchor,
    labelPlacements,
    layoutNetwork,
    NODE_HEIGHT,
    NODE_WIDTH,
    nodeClass,
    primaryCategories,
    primaryTies,
    RING_ASPECT,
    ringLayout,
    shortName,
} from "@partner_relationship/network_layout";

function ring(degree, count, from = 0) {
    return Array.from({ length: count }, (_, index) => ({
        id: from + index,
        name: `Contact ${from + index}`,
        degree,
        is_company: false,
    }));
}

function distance(point) {
    return Math.hypot(point.x, point.y);
}

// Rings are ellipses, so plain distance from the focus does NOT encode degree:
// a point at the flat top of an outer ring is genuinely closer to the origin
// than one at the wide side of an inner one. Undo the squash and the rings are
// nested circles again, which is the invariant that actually has to hold.
function ringRadius(point) {
    return Math.hypot(point.x, point.y / RING_ASPECT);
}

function boxesOverlap(one, other, width, height) {
    return Math.abs(one.x - other.x) < width && Math.abs(one.y - other.y) < height;
}

describe("partner network layout", () => {
    test("the focus sits at the origin", () => {
        const positions = ringLayout([{ id: 1, name: "Focus", degree: 0 }]);

        expect(positions.get(1)).toEqual({ x: 0, y: 0 });
    });

    test("a ring is spread evenly around the focus", () => {
        const positions = ringLayout([{ id: 1, degree: 0 }, ...ring(1, 4, 10)]);

        const radii = [10, 11, 12, 13].map((id) => distance(positions.get(id)));
        for (const radius of radii) {
            expect(Math.round(radius)).toBe(Math.round(radii[0]));
        }
        const distinct = new Set(
            [10, 11, 12, 13].map(
                (id) => `${positions.get(id).x},${positions.get(id).y}`,
            ),
        );
        expect(distinct.size).toBe(4);
    });

    test("a crowded ring widens instead of overlapping its labels", () => {
        const sparse = ringLayout([{ id: 1, degree: 0 }, ...ring(1, 3, 10)]);
        const crowded = ringLayout([{ id: 1, degree: 0 }, ...ring(1, 30, 10)]);

        const arcSparse = (2 * Math.PI * distance(sparse.get(10))) / 3;
        const arcCrowded = (2 * Math.PI * distance(crowded.get(10))) / 30;

        expect(distance(crowded.get(10))).toBeGreaterThan(distance(sparse.get(10)));
        expect(arcCrowded).toBeGreaterThan(NODE_WIDTH);
        expect(arcSparse).toBeGreaterThan(NODE_WIDTH);
    });

    test("an outer ring never falls inside the one before it", () => {
        const positions = ringLayout([
            { id: 1, degree: 0 },
            ...ring(1, 12, 10),
            ...ring(2, 2, 30),
            ...ring(3, 2, 40),
        ]);

        expect(ringRadius(positions.get(30))).toBeGreaterThan(
            ringRadius(positions.get(10)),
        );
        expect(ringRadius(positions.get(40))).toBeGreaterThan(
            ringRadius(positions.get(30)),
        );
    });
});

describe("partner network styling hooks", () => {
    test("the focus and the degree are both on the node", () => {
        const classes = nodeClass({ id: 7, degree: 0, is_company: false }, 7).split(
            " ",
        );

        expect(classes).toInclude("o_partner_network_node");
        expect(classes).toInclude("o_partner_network_focus");
        expect(classes).toInclude("o_partner_network_degree_0");
    });

    test("a far node is not marked as the focus", () => {
        const classes = nodeClass({ id: 9, degree: 2, is_company: true }, 7).split(" ");

        expect(classes).not.toInclude("o_partner_network_focus");
        expect(classes).toInclude("o_partner_network_degree_2");
        expect(classes).toInclude("o_partner_network_company");
    });

    test("a degree past the styled rings still lands on a declared class", () => {
        expect(nodeClass({ id: 9, degree: 7 }, 7)).toInclude(
            "o_partner_network_degree_3",
        );
    });

    test("an edge carries its category", () => {
        expect(edgeClass({ category: "blood" })).toInclude(
            "o_partner_network_category_blood",
        );
        expect(edgeClass({ category: false })).toInclude(
            "o_partner_network_category_other",
        );
    });

    test("a long name is shortened, a short one is left alone", () => {
        expect(shortName("Juan Herrera")).toBe("Juan Herrera");
        expect(shortName("Juan Herrera de la Cruz y Salas").length).toBe(20);
    });
});

describe("joint is reachable and draws", () => {
    let container = null;

    afterEach(() => {
        container?.remove();
        container = null;
    });

    test("the vendored bundle resolves through the import map", async () => {
        const joint = await loadJoint();

        expect(joint.dia).toBeInstanceOf(Object);
        expect(joint.shapes.standard.Rectangle).toBeInstanceOf(Function);
        expect(joint.DirectedGraph).toBeInstanceOf(Object);
    });

    // The placement search computes a point on the link and expects JointJS to
    // put the label's centre there. Worth checking against the library rather
    // than assumed -- labelPlacements reported no collisions while four labels
    // visibly sat on nodes, and the reason was a disagreement about which
    // segment `distance` measures.
    //
    // The boxes here are the real NODE_WIDTH x NODE_HEIGHT on purpose. An
    // earlier version of this used 10x10, where the drawn path and the
    // centre-to-centre line are nearly the same and the bug is invisible.
    test("a link label lands where {distance, offset} says", async () => {
        const { dia, shapes } = await loadJoint();
        container = document.createElement("div");
        document.body.appendChild(container);

        const graph = new dia.Graph({}, { cellNamespace: shapes });
        const one = new shapes.standard.Rectangle({
            position: { x: 0, y: 0 },
            size: { width: NODE_WIDTH, height: NODE_HEIGHT },
        });
        const two = one.clone().position(500, 0);
        const link = new shapes.standard.Link({
            source: { id: one.id },
            target: { id: two.id },
            labels: [
                {
                    position: { distance: 0.5, offset: 40 },
                    attrs: {
                        text: { text: "xxxx", class: "o_partner_network_edge_label" },
                    },
                },
            ],
        });
        graph.addCells([one, two, link]);
        const paper = new dia.Paper({
            el: container,
            model: graph,
            width: 900,
            height: 400,
            cellViewNamespace: shapes,
        });

        const label = container.querySelector(".o_partner_network_edge_label");
        const paperBox = container.querySelector("svg").getBoundingClientRect();
        const box = label.getBoundingClientRect();
        const centre = {
            x: box.left + box.width / 2 - paperBox.left,
            y: box.top + box.height / 2 - paperBox.top,
        };

        // Centres are 500 apart at y = NODE_HEIGHT / 2, and the link is drawn
        // between the two BOUNDARIES -- from x = NODE_WIDTH to x = 500 -- so
        // half way along the drawn path is x = (NODE_WIDTH + 500) / 2, NOT 250.
        // The offset is perpendicular, straight down.
        expect(Math.abs(centre.x - (NODE_WIDTH + 500) / 2)).toBeLessThan(12);
        expect(Math.abs(centre.y - (NODE_HEIGHT / 2 + 40))).toBeLessThan(12);
        paper.remove();
    });

    test("a two-node graph renders as SVG in the DOM", async () => {
        const { dia, shapes } = await loadJoint();
        container = document.createElement("div");
        document.body.appendChild(container);

        const graph = new dia.Graph({}, { cellNamespace: shapes });
        const one = new shapes.standard.Rectangle({
            position: { x: 0, y: 0 },
            size: { width: NODE_WIDTH, height: NODE_HEIGHT },
            attrs: { body: { class: "o_partner_network_node" } },
        });
        const two = one.clone().position(300, 200);
        const link = new shapes.standard.Link({
            source: { id: one.id },
            target: { id: two.id },
            attrs: { line: { class: edgeClass({ category: "blood" }) } },
        });
        graph.addCells([one, two, link]);
        const paper = new dia.Paper({
            el: container,
            model: graph,
            width: 600,
            height: 400,
            cellViewNamespace: shapes,
        });

        expect(container.querySelector("svg")).not.toBe(null);
        expect(container.querySelectorAll(".o_partner_network_node")).toHaveLength(2);
        expect(
            container.querySelectorAll(".o_partner_network_category_blood"),
        ).toHaveLength(1);

        paper.remove();
    });
});

function angleOf(point) {
    const angle = Math.atan2(point.y, point.x);
    return angle < 0 ? angle + 2 * Math.PI : angle;
}

function tie(id, source, target, category, extra = {}) {
    return { id, source, target, category, weight_risk: 0.5, ...extra };
}

describe("partner network wedges", () => {
    const focus = { id: 1, degree: 0 };

    test("a category keeps its members inside one contiguous wedge", () => {
        const nodes = [focus, ...ring(1, 2, 10), ...ring(1, 2, 20)];
        const edges = [
            tie(1, 1, 10, "blood"),
            tie(2, 1, 11, "blood"),
            tie(3, 1, 20, "business"),
            tie(4, 1, 21, "business"),
        ];

        const positions = ringLayout(nodes, edges);

        // blood precedes business in CATEGORY_ORDER, and each holds half the
        // outer nodes, so the two wedges split the circle at pi
        for (const id of [10, 11]) {
            expect(angleOf(positions.get(id))).toBeLessThan(Math.PI);
        }
        for (const id of [20, 21]) {
            expect(angleOf(positions.get(id))).toBeGreaterThan(Math.PI);
        }
    });

    test("a wedge is sized to its membership", () => {
        const nodes = [focus, ...ring(1, 6, 10), ...ring(1, 2, 20)];
        const edges = [
            ...[10, 11, 12, 13, 14, 15].map((id, i) => tie(i + 1, 1, id, "blood")),
            tie(7, 1, 20, "business"),
            tie(8, 1, 21, "business"),
        ];

        const positions = ringLayout(nodes, edges);
        const blood = [10, 11, 12, 13, 14, 15].map((id) => angleOf(positions.get(id)));

        // six of eight outer nodes => three quarters of the circle
        expect(Math.max(...blood)).toBeLessThan(1.5 * Math.PI);
    });

    test("the wedge order is stable regardless of edge order", () => {
        const nodes = [focus, ...ring(1, 2, 10), ...ring(1, 2, 20)];
        const forward = [
            tie(1, 1, 10, "business"),
            tie(2, 1, 11, "business"),
            tie(3, 1, 20, "blood"),
            tie(4, 1, 21, "blood"),
        ];

        const a = ringLayout(nodes, forward);
        const b = ringLayout(nodes, [...forward].reverse());

        for (const id of [10, 11, 20, 21]) {
            expect(a.get(id)).toEqual(b.get(id));
        }
    });

    test("the nearer tie decides the wedge when a contact has two", () => {
        const nodes = [focus, { id: 10, degree: 1 }, { id: 20, degree: 2 }];
        const categories = primaryCategories(nodes, [
            tie(1, 1, 10, "business"),
            tie(2, 10, 20, "blood"),
            tie(3, 1, 20, "ritual"),
        ]);

        // 20 is reachable from the focus (degree 0) and from 10 (degree 1);
        // the lower-degree end wins
        expect(categories.get(20)).toBe("ritual");
        expect(categories.get(10)).toBe("business");
    });

    test("a heavier tie wins at equal distance", () => {
        const nodes = [focus, { id: 10, degree: 1 }];
        const categories = primaryCategories(nodes, [
            tie(1, 1, 10, "business", { weight_risk: 0.2 }),
            tie(2, 1, 10, "blood", { weight_risk: 0.9 }),
        ]);

        expect(categories.get(10)).toBe("blood");
    });

    test("a tie of no category still lands in a wedge", () => {
        const nodes = [focus, { id: 10, degree: 1 }];
        const positions = ringLayout(nodes, [tie(1, 1, 10, false)]);

        expect(positions.has(10)).toBe(true);
        expect(distance(positions.get(10))).toBeGreaterThan(0);
        expect(CATEGORY_ORDER).not.toInclude("other");
    });

    test("neighbouring wedges are separated by a gutter", () => {
        const nodes = [focus, ...ring(1, 3, 10), ...ring(1, 3, 20)];
        const edges = [
            ...[10, 11, 12].map((id, i) => tie(i + 1, 1, id, "blood")),
            ...[20, 21, 22].map((id, i) => tie(i + 4, 1, id, "business")),
        ];

        const positions = ringLayout(nodes, edges);
        const blood = [10, 11, 12].map((id) => angleOf(positions.get(id)));
        const business = [20, 21, 22].map((id) => angleOf(positions.get(id)));

        // the two wedges split at pi; neither reaches the boundary
        expect(Math.max(...blood)).toBeLessThan(Math.PI - 0.02);
        expect(Math.min(...business)).toBeGreaterThan(Math.PI + 0.02);
    });

    test("a lone wedge keeps the whole circle", () => {
        const nodes = [focus, ...ring(1, 4, 10)];
        const edges = [10, 11, 12, 13].map((id, i) => tie(i + 1, 1, id, "blood"));

        const withEdges = ringLayout(nodes, edges);
        const withNone = ringLayout(nodes);

        // one category means no neighbour to separate from, so the gutter is
        // not taken and the placement matches the plain concentric layout
        for (const id of [10, 11, 12, 13]) {
            expect(withEdges.get(id)).toEqual(withNone.get(id));
        }
    });

    test("edges between two nodes on the same ring classify neither", () => {
        const nodes = [focus, ...ring(1, 2, 10)];
        const categories = primaryCategories(nodes, [tie(1, 10, 11, "blood")]);

        expect(categories.size).toBe(0);
    });
});

describe("partner network filtering", () => {
    // juan -1- maria -2- pedro -3- lucia, plus a business tie hanging off juan.
    function network() {
        return {
            focus_id: 1,
            reached_degree: 3,
            nodes: [
                { id: 1, name: "Juan", degree: 0 },
                { id: 2, name: "Maria", degree: 1 },
                { id: 3, name: "Pedro", degree: 2 },
                { id: 4, name: "Lucia", degree: 3 },
                { id: 5, name: "Banco", degree: 1 },
            ],
            edges: [
                tie(1, 1, 2, "affinity"),
                tie(2, 2, 3, "ritual"),
                tie(3, 3, 4, "agricultural"),
                tie(4, 1, 5, "business"),
            ],
        };
    }

    const every = new Set(["affinity", "ritual", "agricultural", "business"]);

    function idsOf(result) {
        return result.nodes.map((node) => node.id).sort((a, b) => a - b);
    }

    test("the whole network with every category is the network itself", () => {
        const source = network();
        const result = filterNetwork(source, { degree: 3, categories: every });

        expect(idsOf(result)).toEqual([1, 2, 3, 4, 5]);
        expect(result.edges.map((edge) => edge.id)).toEqual([1, 2, 3, 4]);
        expect(result.nodes.map((node) => node.degree)).toEqual(
            source.nodes.map((node) => node.degree),
        );
    });

    test("a degree ceiling drops the ring beyond it", () => {
        const result = filterNetwork(network(), { degree: 2, categories: every });

        expect(idsOf(result)).toEqual([1, 2, 3, 5]);
    });

    // The server refuses to emit an edge whose far end carries no degree,
    // because that node sits at an unknown distance from the focus. Narrowing
    // here has to make the same refusal or it draws exactly those nodes back in.
    test("an edge leaving the last kept ring is dropped with it", () => {
        const result = filterNetwork(network(), { degree: 2, categories: every });

        expect(result.edges.map((edge) => edge.id)).toEqual([1, 2, 4]);
        for (const edge of result.edges) {
            expect(idsOf(result)).toInclude(edge.source);
            expect(idsOf(result)).toInclude(edge.target);
        }
    });

    test("hiding a category removes what only it reached", () => {
        const result = filterNetwork(network(), {
            degree: 3,
            categories: new Set(["affinity", "ritual", "agricultural"]),
        });

        expect(idsOf(result)).toEqual([1, 2, 3, 4]);
        expect(idsOf(result)).not.toInclude(5);
    });

    // Hiding the nearest tie is not a matter of hiding one line: everything
    // behind it was reached THROUGH it, so it leaves with it rather than
    // floating at a degree nothing supports any more.
    test("hiding a near category takes the chain behind it", () => {
        const result = filterNetwork(network(), {
            degree: 3,
            categories: new Set(["ritual", "agricultural", "business"]),
        });

        expect(idsOf(result)).toEqual([1, 5]);
    });

    test("a node reached only by a longer route moves to its real ring", () => {
        const source = network();
        source.nodes.push({ id: 6, name: "Rosa", degree: 1 });
        source.edges.push(tie(5, 1, 6, "business"), tie(6, 2, 6, "affinity"));

        const both = filterNetwork(source, { degree: 3, categories: every });
        const withoutBusiness = filterNetwork(source, {
            degree: 3,
            categories: new Set(["affinity", "ritual", "agricultural"]),
        });

        const degreeOf = (result, id) =>
            result.nodes.find((node) => node.id === id).degree;

        expect(degreeOf(both, 6)).toBe(1);
        expect(degreeOf(withoutBusiness, 6)).toBe(2);
    });

    test("hiding every category leaves the focus alone", () => {
        const result = filterNetwork(network(), { degree: 3, categories: new Set() });

        expect(idsOf(result)).toEqual([1]);
        expect(result.edges).toEqual([]);
    });

    test("the focus survives a degree ceiling of zero", () => {
        const result = filterNetwork(network(), { degree: 0, categories: every });

        expect(idsOf(result)).toEqual([1]);
        expect(result.edges).toEqual([]);
    });

    test("filtering leaves the network it was given untouched", () => {
        const source = network();
        filterNetwork(source, { degree: 1, categories: new Set(["affinity"]) });

        expect(source.nodes).toHaveLength(5);
        expect(source.edges).toHaveLength(4);
        expect(source.nodes[2].degree).toBe(2);
    });
});

describe("partner network packing", () => {
    const focus = { id: 1, degree: 0 };

    function crowd(count, degree, from) {
        return Array.from({ length: count }, (_, index) => ({
            id: from + index,
            name: `Contact ${from + index}`,
            degree,
        }));
    }

    function extent(positions) {
        const points = [...positions.values()];
        const xs = points.map((point) => point.x);
        const ys = points.map((point) => point.y);
        return {
            width: Math.max(...xs) - Math.min(...xs) + NODE_WIDTH,
            height: Math.max(...ys) - Math.min(...ys) + NODE_HEIGHT,
        };
    }

    function collisions(positions) {
        const points = [...positions.values()];
        let found = 0;
        for (let i = 0; i < points.length; i++) {
            for (let j = i + 1; j < points.length; j++) {
                if (boxesOverlap(points[i], points[j], NODE_WIDTH, NODE_HEIGHT)) {
                    found += 1;
                }
            }
        }
        return found;
    }

    // The property the ring's radius is grown to establish. The formula this
    // replaced predicted a radius from arc length and could leave pairs sitting
    // on top of each other once the rings were flattened; this asserts the
    // outcome instead of the formula.
    test("no two nodes overlap, however crowded the ring", () => {
        for (const count of [2, 5, 12, 30, 60]) {
            const positions = ringLayout([focus, ...crowd(count, 1, 10)]);

            expect(collisions(positions)).toBe(0);
        }
    });

    test("nothing overlaps across three crowded rings", () => {
        const positions = ringLayout([
            focus,
            ...crowd(11, 1, 100),
            ...crowd(9, 2, 200),
            ...crowd(7, 3, 300),
        ]);

        expect(collisions(positions)).toBe(0);
    });

    test("nothing overlaps when the rings are split into wedges", () => {
        const nodes = [focus, ...crowd(6, 1, 10), ...crowd(6, 1, 20)];
        const edges = [
            ...[10, 11, 12, 13, 14, 15].map((id, i) => tie(i + 1, 1, id, "blood")),
            ...[20, 21, 22, 23, 24, 25].map((id, i) => tie(i + 7, 1, id, "business")),
        ];

        expect(collisions(ringLayout(nodes, edges))).toBe(0);
    });

    // The reason the rings are ellipses at all: node boxes are far wider than
    // they are tall, so a circle over-spends height, and height is what binds
    // the fit in a canvas wider than it is tall.
    test("the drawing is wider than it is tall", () => {
        const { width, height } = extent(
            ringLayout([focus, ...crowd(11, 1, 100), ...crowd(9, 2, 200)]),
        );

        expect(width).toBeGreaterThan(height);
    });

    test("a ring is an ellipse of the declared aspect, not a circle", () => {
        const positions = ringLayout([focus, ...crowd(16, 1, 10)]);
        const radii = [...Array(16).keys()].map((index) =>
            Math.hypot(
                positions.get(10 + index).x,
                positions.get(10 + index).y / RING_ASPECT,
            ),
        );

        // Positions are rounded to whole pixels and y is stored already
        // squashed, so undoing the squash multiplies that rounding by 1/aspect.
        // The tolerance is that noise (~1px here), not slack in the invariant.
        for (const radius of radii) {
            expect(Math.abs(radius - radii[0])).toBeLessThan(3);
        }
        expect(RING_ASPECT).toBeLessThan(1);
    });

    // Growing a ring must not push its members out of the sector their category
    // owns, or the radius search would quietly undo the grouping it is laid out
    // to show.
    test("growing a ring leaves every node in its own wedge", () => {
        const nodes = [focus, ...crowd(10, 1, 10), ...crowd(10, 1, 20)];
        const edges = [
            ...Array.from({ length: 10 }, (_, i) => tie(i + 1, 1, 10 + i, "blood")),
            ...Array.from({ length: 10 }, (_, i) => tie(i + 11, 1, 20 + i, "business")),
        ];
        const positions = ringLayout(nodes, edges);
        const angleOf = (id) => {
            const point = positions.get(id);
            const angle = Math.atan2(point.y / RING_ASPECT, point.x);
            return angle < 0 ? angle + 2 * Math.PI : angle;
        };
        const blood = [...Array(10).keys()].map((i) => angleOf(10 + i));
        const business = [...Array(10).keys()].map((i) => angleOf(20 + i));

        expect(Math.max(...blood)).toBeLessThan(Math.PI);
        expect(Math.min(...business)).toBeGreaterThan(Math.PI);
    });
});

describe("partner network branches", () => {
    const focus = { id: 1, degree: 0 };

    function angleOfPoint(point) {
        const angle = Math.atan2(point.y / RING_ASPECT, point.x);
        return angle < 0 ? angle + 2 * Math.PI : angle;
    }

    // The shape that broke: a company reached into a family through one
    // shareholder. BOTH first-degree ties are "business", so grouping by
    // category crushed them into one wedge while the shareholder's relatives
    // fanned out across every other wedge -- putting a contact nowhere near the
    // person it descends from, and sending its edge across the whole drawing.
    function companyNetwork() {
        const nodes = [
            focus,
            { id: 10, degree: 1 }, // the shareholder
            { id: 11, degree: 1 }, // the other company
            { id: 20, degree: 2 }, // the shareholder's blood relative
            { id: 21, degree: 2 }, // ...and affinity
            { id: 22, degree: 2 }, // ...and ritual
            { id: 30, degree: 2 }, // the other company's business contact
        ];
        const edges = [
            tie(1, 1, 10, "business"),
            tie(2, 1, 11, "business"),
            tie(3, 10, 20, "blood"),
            tie(4, 10, 21, "affinity"),
            tie(5, 10, 22, "ritual"),
            tie(6, 11, 30, "business"),
        ];
        return { nodes, edges };
    }

    test("the tie that reached a contact names its parent, not just its kind", () => {
        const { nodes, edges } = companyNetwork();
        const ties = primaryTies(nodes, edges);

        expect(ties.get(20).parentId).toBe(10);
        expect(ties.get(20).category).toBe("blood");
        expect(ties.get(30).parentId).toBe(11);
    });

    // Walk each node up to the first-degree ancestor it descends from.
    function branchOf(id, ties) {
        let cursor = id;
        while (ties.get(cursor) && ties.get(cursor).parentId !== 1) {
            cursor = ties.get(cursor).parentId;
        }
        return cursor;
    }

    // The property grouping by category lost, stated the way it can actually be
    // measured from positions alone: sweep the circle and each branch is one
    // unbroken run. Anything else means a contact from another branch sits
    // between a parent and its own children, which is what sent edges across
    // the middle of the drawing.
    test("each branch occupies one unbroken arc", () => {
        const { nodes, edges } = companyNetwork();
        const positions = ringLayout(nodes, edges);
        const ties = primaryTies(nodes, edges);

        const sweep = nodes
            .filter((node) => node.degree > 0)
            .map((node) => ({
                branch: branchOf(node.id, ties),
                angle: angleOfPoint(positions.get(node.id)),
            }))
            .sort((one, other) => one.angle - other.angle)
            .map((entry) => entry.branch);

        const runs = sweep.filter((branch, index) => branch !== sweep[index - 1]);

        expect(new Set(sweep).size).toBe(2);
        expect(runs.length).toBe(2);
    });

    test("a branch's own root shares its arc with its children", () => {
        const { nodes, edges } = companyNetwork();
        const positions = ringLayout(nodes, edges);
        const angles = new Map(
            nodes
                .filter((node) => node.degree > 0)
                .map((node) => [node.id, angleOfPoint(positions.get(node.id))]),
        );

        // 10 has three children and 11 has one, so 10 is given three quarters
        // of the circle -- the arcs are sized by what hangs below them, not
        // split evenly -- and 11 with its single child sits beyond all of them.
        for (const id of [20, 21, 22, 10]) {
            expect(angles.get(id)).toBeLessThan(angles.get(11));
        }
        expect(angles.get(30)).toBeGreaterThan(angles.get(22));
    });

    test("siblings stay ordered by category, so colours still cluster", () => {
        const nodes = [
            focus,
            { id: 10, degree: 1 },
            { id: 11, degree: 1 },
            { id: 12, degree: 1 },
        ];
        // declared business, blood, affinity -- the layout must not preserve
        // that order, it must impose CATEGORY_ORDER on it
        const edges = [
            tie(1, 1, 10, "business"),
            tie(2, 1, 11, "blood"),
            tie(3, 1, 12, "affinity"),
        ];
        const positions = ringLayout(nodes, edges);
        const order = [11, 12, 10].map((id) => angleOfPoint(positions.get(id)));

        expect(order[0]).toBeLessThan(order[1]);
        expect(order[1]).toBeLessThan(order[2]);
        expect(CATEGORY_ORDER.indexOf("blood")).toBeLessThan(
            CATEGORY_ORDER.indexOf("business"),
        );
    });

    test("a wide branch is given more of the circle than a narrow one", () => {
        const nodes = [
            focus,
            { id: 10, degree: 1 },
            { id: 11, degree: 1 },
            ...[20, 21, 22, 23].map((id) => ({ id, degree: 2 })),
            { id: 30, degree: 2 },
        ];
        const edges = [
            tie(1, 1, 10, "business"),
            tie(2, 1, 11, "business"),
            ...[20, 21, 22, 23].map((id, i) => tie(i + 3, 10, id, "blood")),
            tie(7, 11, 30, "blood"),
        ];
        const positions = ringLayout(nodes, edges);
        const spread = (ids) => {
            const angles = ids.map((id) => angleOfPoint(positions.get(id)));
            return Math.max(...angles) - Math.min(...angles);
        };

        expect(spread([20, 21, 22, 23])).toBeGreaterThan(spread([30, 30]));
        expect(angleOfPoint(positions.get(10))).toBeLessThan(
            angleOfPoint(positions.get(11)),
        );
    });
});

describe("partner network edge labels", () => {
    const focus = { id: 1, degree: 0 };
    const CHAR = 6.2;
    const LABEL_HEIGHT = 15;
    const PADDING = 6;

    function labelBoxes(nodes, edges) {
        const { positions, placements } = layoutNetwork(nodes, edges);
        return {
            positions,
            boxes: edges
                .filter(
                    (edge) => positions.has(edge.source) && positions.has(edge.target),
                )
                .map((edge) => {
                    const placement = placements.get(edge.id);
                    // Ask the layout where the label goes rather than
                    // re-deriving it: a link is drawn boundary to boundary, not
                    // centre to centre, and duplicating that here is how this
                    // checker came to report zero collisions while four labels
                    // sat on nodes.
                    const anchor = labelAnchor(
                        positions.get(edge.source),
                        positions.get(edge.target),
                        placement,
                    );
                    return {
                        id: edge.id,
                        ...anchor,
                        width: (edge.label || "").length * CHAR + PADDING * 2,
                        height: LABEL_HEIGHT,
                        distance: placement.distance,
                        offset: placement.offset,
                    };
                }),
        };
    }

    function hits(one, other) {
        return (
            Math.abs(one.x - other.x) < (one.width + other.width) / 2 &&
            Math.abs(one.y - other.y) < (one.height + other.height) / 2
        );
    }

    function collisions(nodes, edges) {
        const { positions, boxes } = labelBoxes(nodes, edges);
        const nodeBoxes = nodes
            .filter((node) => positions.has(node.id))
            .map((node) => ({
                ...positions.get(node.id),
                width: NODE_WIDTH,
                height: NODE_HEIGHT,
            }));
        let overNode = 0;
        let overLabel = 0;
        for (const [index, box] of boxes.entries()) {
            if (nodeBoxes.some((node) => hits(box, node))) {
                overNode += 1;
            }
            if (boxes.slice(0, index).some((other) => hits(box, other))) {
                overLabel += 1;
            }
        }
        return { overNode, overLabel };
    }

    const WORDINGS = [
        "brother of",
        "husband of",
        "compadre of",
        "father of",
        "padrino of",
        "shares a household with",
        "guarantor of",
        "shareholder of",
        "grows crop together with",
        "member of the same ejido as",
        "sister of",
        "cousin of",
    ];

    function fan(count, label = null) {
        const nodes = [focus];
        const edges = [];
        for (let index = 0; index < count; index++) {
            nodes.push({ id: 10 + index, degree: 1 });
            edges.push({
                id: index + 1,
                source: 1,
                target: 10 + index,
                category: CATEGORY_ORDER[index % CATEGORY_ORDER.length],
                label: label ?? WORDINGS[index % WORDINGS.length],
                weight_risk: 0.5,
            });
        }
        return { nodes, edges };
    }

    // A single fixed ratio along the link put 9 of 21 labels on top of a node
    // on a real network: 0.72 of a short link is INSIDE the box at its far end,
    // so the anchor was under the very node it named. The anchor is read from
    // the box's extent along the link now, and the search moves outward from
    // there only when it must.
    test("no label sits on a node, at any fan size", () => {
        for (const count of [2, 3, 5, 8, 12, 16, 30]) {
            const { nodes, edges } = fan(count);
            expect(collisions(nodes, edges).overNode).toBe(0);
        }
    });

    test("no label sits on another label", () => {
        for (const count of [5, 12, 16, 30]) {
            const { nodes, edges } = fan(count);
            expect(collisions(nodes, edges).overLabel).toBe(0);
        }
    });

    test("labels clear the nodes across three rings", () => {
        const nodes = [focus];
        const edges = [];
        let id = 10;
        for (let branch = 0; branch < 5; branch++) {
            nodes.push({ id, degree: 1 });
            edges.push({
                id,
                source: 1,
                target: id,
                category: "blood",
                label: "brother of",
            });
            const parent = id;
            id += 1;
            for (let child = 0; child < 2; child++) {
                nodes.push({ id, degree: 2 });
                edges.push({
                    id,
                    source: parent,
                    target: id,
                    category: "affinity",
                    label: "shares a household with",
                });
                id += 1;
            }
        }
        const { overNode, overLabel } = collisions(nodes, edges);

        expect(overNode).toBe(0);
        expect(overLabel).toBe(0);
    });

    test("a label clears both ends of its own link", () => {
        const { nodes, edges } = fan(6);
        const { positions, boxes } = labelBoxes(nodes, edges);

        for (const box of boxes) {
            const edge = edges.find((candidate) => candidate.id === box.id);
            for (const end of [edge.source, edge.target]) {
                const node = {
                    ...positions.get(end),
                    width: NODE_WIDTH,
                    height: NODE_HEIGHT,
                };
                expect(hits(box, node)).toBe(false);
            }
        }
    });

    // A symmetric tie is stored once, from whichever end recorded it, so the
    // same relationship can arrive with source and target swapped. Placement
    // must not notice: the two readings are mirror images about the middle of
    // the drawn path, which is what makes the anchor a property of the GEOMETRY
    // rather than of the row.
    //
    // Measured on a crowded ring on purpose. On a short link the two node boxes
    // leave less drawn path than the label is wide, no point on it clears
    // either box, and the anchor is deliberately the middle -- where a mirror
    // test cannot tell the two readings apart.
    test("a label lands the same way round whichever end stored the tie", () => {
        const { nodes, edges } = fan(20);
        const reversed = edges.map((edge) =>
            edge.id === 1
                ? { ...edge, source: edge.target, target: edge.source }
                : edge,
        );

        const forward = layoutNetwork(nodes, edges).placements.get(1);
        const backward = layoutNetwork(nodes, reversed).placements.get(1);

        // HOOT's toBeCloseTo takes {margin}, not Jest's digit count -- a bare
        // number lands in `options`, leaving the default margin of 1, which on
        // values in [0, 1] asserts nothing at all.
        expect(forward.distance + backward.distance).toBeCloseTo(1, { margin: 0.0001 });
        expect(forward.distance).not.toBeCloseTo(0.5, { margin: 0.05 });
    });

    test("placement does not depend on the order edges arrive in", () => {
        const { nodes, edges } = fan(12);
        const positions = ringLayout(nodes, edges);
        const forward = labelPlacements(nodes, edges, positions);
        const backward = labelPlacements(nodes, [...edges].reverse(), positions);

        for (const edge of edges) {
            expect(backward.get(edge.id)).toEqual(forward.get(edge.id));
        }
    });

    // The worst case is real but rare: every tie on a tight ring carrying the
    // longest wording in the vocabulary at once. The search cannot clear that,
    // and takes its least-colliding candidate rather than dropping a label --
    // a label pushed somewhere awkward still names its edge, a missing one
    // loses the relationship.
    test("every edge is given a placement, even when nothing clears", () => {
        const { nodes, edges } = fan(6, "member of the same ejido as");
        const positions = ringLayout(nodes, edges);
        const placements = labelPlacements(nodes, edges, positions);

        expect(placements.size).toBe(edges.length);
        for (const edge of edges) {
            const { distance, offset } = placements.get(edge.id);
            expect(Number.isFinite(distance)).toBe(true);
            expect(Number.isFinite(offset)).toBe(true);
        }
    });
});
