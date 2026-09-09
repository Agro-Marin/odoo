// @ts-check
/** @odoo-module native */

import {
    Component,
    onWillStart,
    onWillUnmount,
    onWillUpdateProps,
    useEffect,
    useExternalListener,
    useRef,
    useState,
} from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";

import { loadJoint } from "./lib/joint.js";
import {
    CANVAS_PADDING,
    edgeClass,
    filterNetwork,
    halfExtentAround,
    layoutNetwork,
    NODE_HEIGHT,
    NODE_WIDTH,
    labelClass,
    nodeClass,
    primaryTies,
    shortName,
} from "./network_layout.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const ZOOM_STEP = 1.25;
const ZOOM_MIN = 0.2;
const ZOOM_MAX = 3;
const CANVAS_MARGIN = 16;
const CANVAS_MIN_HEIGHT = 420;
// Small networks are drawn above their natural size rather than marooned in
// the middle of a large canvas.
const FIT_MAX_SCALE = 1.25;

export class PartnerNetwork extends Component {
    static template = "partner_relationship.PartnerNetwork";
    static props = {
        record: Object,
        readonly: { type: Boolean, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.canvas = useRef("canvas");
        this.box = useRef("box");
        this.state = useState({
            status: "idle",
            error: "",
            degree: 0,
            reachedDegree: 0,
            categories: [],
            categoryOn: {},
            zoom: 1,
            focusId: null,
            focusName: "",
        });
        this.paper = null;
        this.drawToken = 0;
        useEffect(
            () => {
                if (this.state.status === "ready") {
                    this.draw();
                }
            },
            () => [this.state.status, this.drawToken],
        );
        onWillStart(() => this.load());
        onWillUpdateProps(async (nextProps) => {
            if (nextProps.record.resId !== this.props.record.resId) {
                await this.load(nextProps.record.resId);
            }
        });
        useExternalListener(window, "resize", () => this.onResize());
        onWillUnmount(() => this.teardown());
    }

    get resId() {
        return this.props.record.resId;
    }

    async load(resId = this.resId) {
        this.teardown();
        if (!resId) {
            this.state.status = "unsaved";
            return;
        }
        this.state.status = "loading";
        try {
            const [network] = await Promise.all([
                this.orm.call("res.partner", "get_relation_network", [[resId]]),
                loadJoint(),
            ]);
            this.network = network;
            this.state.focusId = network.focus_id;
            this.state.focusName =
                network.nodes.find((node) => node.id === network.focus_id)?.name ?? "";
            this.state.reachedDegree = network.reached_degree;
            this.state.degree = network.reached_degree;
            this.state.categories = network.categories;
            this.state.categoryOn = Object.fromEntries(
                network.categories.map((category) => [category.key, true]),
            );
            this.state.zoom = 1;
            this.state.status = network.edges.length ? "ready" : "empty";
        } catch (error) {
            this.state.status = "error";
            this.state.error = error.message || String(error);
            return;
        }
        this.drawToken += 1;
    }

    get visible() {
        return filterNetwork(this.network, {
            degree: this.state.degree,
            categories: this.selectedFrom(this.state.categoryOn),
        });
    }

    get countRelated() {
        return this.visible.nodes.length - 1;
    }

    setDegree(degree) {
        this.state.degree = degree;
        this.drawToken += 1;
    }

    toggleCategory(key) {
        this.state.categoryOn[key] = !this.state.categoryOn[key];
        this.drawToken += 1;
    }

    setEveryCategory(isOn) {
        for (const category of this.state.categories) {
            this.state.categoryOn[category.key] = isOn;
        }
        this.drawToken += 1;
    }

    onlyCategory(key) {
        for (const category of this.state.categories) {
            this.state.categoryOn[category.key] = category.key === key;
        }
        this.drawToken += 1;
    }

    get isEveryCategoryOn() {
        return this.state.categories.every(
            (category) => this.state.categoryOn[category.key],
        );
    }

    get isNoCategoryOn() {
        return this.state.categories.every(
            (category) => !this.state.categoryOn[category.key],
        );
    }

    get countPerCategory() {
        const drawn = this.visible;
        const counts = Object.fromEntries(
            this.state.categories.map((category) => [category.key, 0]),
        );
        for (const tie of primaryTies(drawn.nodes, drawn.edges).values()) {
            if (tie.category in counts) {
                counts[tie.category] += 1;
            }
        }
        return counts;
    }

    selectedFrom(categoryOn) {
        const selected = new Set(
            Object.entries(categoryOn)
                .filter(([, isOn]) => isOn)
                .map(([key]) => key),
        );
        selected.add("other");
        return selected;
    }

    teardown() {
        this.paper?.remove();
        this.paper = null;
    }

    async draw() {
        this.teardown();
        const host = this.canvas.el;
        if (!host) {
            return;
        }
        const element = document.createElement("div");
        host.replaceChildren(element);
        const { dia, shapes } = await loadJoint();
        const network = this.visible;
        const { positions, placements } = layoutNetwork(network.nodes, network.edges);
        const graph = new dia.Graph({}, { cellNamespace: shapes });
        const cellPerId = new Map();

        for (const node of network.nodes) {
            const { x, y } = positions.get(node.id);
            const cell = new shapes.standard.Rectangle({
                position: { x: x - NODE_WIDTH / 2, y: y - NODE_HEIGHT / 2 },
                size: { width: NODE_WIDTH, height: NODE_HEIGHT },
                attrs: {
                    body: {
                        rx: 4,
                        ry: 4,
                        class: nodeClass(node, network.focus_id),
                    },
                    label: {
                        text: shortName(node.name),
                        class: labelClass(node, network.focus_id),
                    },
                },
            });
            cell.set("partnerId", node.id);
            cell.set("partnerName", node.name);
            cellPerId.set(node.id, cell);
            graph.addCell(cell);
        }

        for (const edge of network.edges) {
            const source = cellPerId.get(edge.source);
            const target = cellPerId.get(edge.target);
            const link = new shapes.standard.Link({
                source: { id: source.id },
                target: { id: target.id },
                attrs: {
                    line: {
                        class: edgeClass(edge),
                        ...(edge.symmetric ? { targetMarker: { d: "M 0 0" } } : {}),
                    },
                },
                labels: [
                    {
                        position: placements.get(edge.id) ?? { distance: 0.5 },
                        attrs: {
                            text: {
                                text: edge.label,
                                class: "o_partner_network_edge_label",
                            },
                            rect: { class: "o_partner_network_edge_label_bg" },
                        },
                    },
                ],
            });
            graph.addCell(link);
        }

        this.paper = new dia.Paper({
            el: element,
            model: graph,
            width: "100%",
            height: "100%",
            gridSize: 1,
            background: { color: "transparent" },
            interactive: false,
            cellViewNamespace: shapes,
        });
        this.halfExtent = halfExtentAround(positions);
        this.labelNodes(cellPerId);
        this.resizeBox();
        this.fit();
        this.paper.on("element:pointerclick", (view) => {
            this.focusOn(view.model.get("partnerId"));
        });
        this.paper.on("element:pointerdblclick", (view) => {
            this.openPartner(view.model.get("partnerId"));
        });
        this.paper.on("blank:pointerdown", (event) => this.startPan(event));
        this.paper.on("blank:mousewheel", (event, x, y, delta) =>
            this.wheelZoom(event, delta),
        );
        this.paper.on("cell:mousewheel", (view, event, x, y, delta) =>
            this.wheelZoom(event, delta),
        );
    }

    labelNodes(cellPerId) {
        for (const cell of cellPerId.values()) {
            const view = this.paper.findViewByModel(cell);
            if (!view) {
                continue;
            }
            const title = document.createElementNS(SVG_NS, "title");
            title.textContent = cell.get("partnerName");
            view.el.appendChild(title);
        }
    }

    resizeBox() {
        const box = this.box.el;
        if (!box || !box.closest(".o_partner_network_full")) {
            return false;
        }
        let below = 0;
        for (
            let sibling = box.nextElementSibling;
            sibling;
            sibling = sibling.nextElementSibling
        ) {
            below += sibling.getBoundingClientRect().height;
        }
        const room = Math.round(
            window.innerHeight -
                box.getBoundingClientRect().top -
                below -
                CANVAS_MARGIN,
        );
        const height = `${Math.max(room, CANVAS_MIN_HEIGHT)}px`;
        if (box.style.height === height) {
            return false;
        }
        box.style.height = height;
        return true;
    }

    onResize() {
        if (this.resizeBox() && this.paper) {
            this.fit();
        }
    }

    // Put the CONTACT BEING LOOKED AT in the middle, not the middle of the ink.
    //
    // transformToFitContent centres the content's bounding box, which is only
    // the focus when the graph is balanced around it. It rarely is: open a
    // contact who sits at the edge of someone else's family -- reached through
    // one cousin, whose own subtree carries nine of the eleven contacts -- and
    // the mass sits to one side, so the box centres on the hub and the contact
    // whose page this is drifts to the rim.
    //
    // Fitting a box centred on the focus fixes that by construction: the focus
    // is the origin of the layout, so it lands dead centre and empty space
    // opens opposite whatever branch is heaviest. It costs a little scale --
    // measured across three real networks, 125/125/109% became 125/114/99% --
    // which is a fair price for the diagram answering the question it was
    // opened to answer.
    fit() {
        const element = this.paper.el;
        const width = element.clientWidth;
        const height = element.clientHeight;
        const half = this.halfExtent;
        const scale = Math.min(
            Math.max(
                Math.min(
                    (width - CANVAS_PADDING * 2) / (half.x * 2),
                    (height - CANVAS_PADDING * 2) / (half.y * 2),
                ),
                ZOOM_MIN,
            ),
            FIT_MAX_SCALE,
        );
        this.paper.scale(scale, scale);
        // The focus sits at the layout's origin, and a point at the origin lands
        // wherever the translation puts it, so this IS "centre the focus".
        this.paper.translate(width / 2, height / 2);
        this.state.zoom = scale;
    }

    setZoom(zoom, center = null) {
        const next = Math.min(Math.max(zoom, ZOOM_MIN), ZOOM_MAX);
        const previous = this.paper.scale().sx;
        if (next === previous) {
            return;
        }
        const anchor = center ?? {
            x: this.paper.el.clientWidth / 2,
            y: this.paper.el.clientHeight / 2,
        };
        const translate = this.paper.translate();
        this.paper.scale(next, next);
        this.paper.translate(
            anchor.x - ((anchor.x - translate.tx) * next) / previous,
            anchor.y - ((anchor.y - translate.ty) * next) / previous,
        );
        this.state.zoom = next;
    }

    zoomBy(factor) {
        this.setZoom(this.paper.scale().sx * factor);
    }

    wheelZoom(event, delta) {
        const original = event.originalEvent ?? event;
        if (!original.ctrlKey && !original.metaKey) {
            return;
        }
        original.preventDefault();
        const box = this.paper.el.getBoundingClientRect();
        this.setZoom(this.paper.scale().sx * (delta > 0 ? ZOOM_STEP : 1 / ZOOM_STEP), {
            x: original.clientX - box.left,
            y: original.clientY - box.top,
        });
    }

    startPan(event) {
        const original = event.originalEvent ?? event;
        const start = this.paper.translate();
        const fromX = original.clientX;
        const fromY = original.clientY;
        const onMove = (move) => {
            this.paper.translate(
                start.tx + move.clientX - fromX,
                start.ty + move.clientY - fromY,
            );
        };
        const onUp = () => {
            document.removeEventListener("pointermove", onMove);
            document.removeEventListener("pointerup", onUp);
        };
        document.addEventListener("pointermove", onMove);
        document.addEventListener("pointerup", onUp);
    }

    get degrees() {
        return Array.from(
            { length: this.state.reachedDegree },
            (_, index) => index + 1,
        );
    }

    get isMoved() {
        return this.state.focusId !== this.resId;
    }

    get zoomPercent() {
        return `${Math.round(this.state.zoom * 100)}%`;
    }

    get emptyMessage() {
        return this.network?.nodes.length > 1
            ? _t("No relationship links these contacts.")
            : _t("This contact has no recorded relationships.");
    }

    async focusOn(partnerId) {
        if (partnerId && partnerId !== this.state.focusId) {
            await this.load(partnerId);
        }
    }

    async recentre() {
        await this.load(this.resId);
    }

    openPartner(partnerId) {
        if (!partnerId) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "res.partner",
            res_id: partnerId,
            views: [[false, "form"]],
        });
    }
}

registry.category("view_widgets").add("partner_network", { component: PartnerNetwork });
