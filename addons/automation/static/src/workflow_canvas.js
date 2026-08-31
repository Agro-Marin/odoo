/** @odoo-module native */

import {
    Component,
    onWillStart,
    onWillUnmount,
    onWillUpdateProps,
    useEffect,
    useRef,
    useState,
} from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/translation";

import {
    canConnect,
    conditionLabel,
    linkClasses,
    NODE_HEIGHT,
    NODE_WIDTH,
    nodeClasses,
    shortName,
} from "./workflow_graph.js";

const PADDING = 32;
const CHANNEL_PREFIX = "automation.workflow/";
const UPDATE_TYPE = "automation.workflow/update";

function log(...parts) {
    browser.console.debug("[workflow-canvas]", ...parts);
}

let jointPromise = null;

function loadJoint() {
    jointPromise ??= import("joint").catch((error) => {
        jointPromise = null;
        throw error;
    });
    return jointPromise;
}

export class WorkflowCanvas extends Component {
    static template = "automation.WorkflowCanvas";
    static props = {
        record: Object,
        readonly: { type: Boolean, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.bus = useService("bus_service");
        this.canvas = useRef("canvas");
        this.state = useState({
            status: "idle",
            error: "",
            countNode: 0,
            countEdge: 0,
            selectedEdgeId: null,
        });
        this.paper = null;
        this.graph = null;
        this.drawToken = 0;
        this.listening = null;
        this.onWorkflowUpdate = ({ automation_id }) => {
            log("bus", automation_id, "mine:", automation_id === this.resId);
            if (automation_id === this.resId) {
                this.load();
            }
        };
        useEffect(
            () => {
                if (this.state.status === "ready") {
                    this.draw();
                }
            },
            () => [this.state.status, this.drawToken],
        );
        onWillStart(async () => {
            await this.load();
            this.listen();
        });
        onWillUpdateProps(async (nextProps) => {
            if (nextProps.record.resId !== this.resId) {
                this.stopListening();
                await this.load(nextProps.record.resId);
                this.listen(nextProps.record.resId);
            }
        });
        onWillUnmount(() => {
            this.stopListening();
            this.teardown();
        });
    }

    get resId() {
        return this.props.record.resId;
    }

    get isEditable() {
        return !this.props.readonly && !this.props.record.isNew;
    }

    async load() {
        this.teardown();
        if (!this.resId) {
            this.state.status = "unsaved";
            return;
        }
        this.state.status = "loading";
        try {
            const [payload, joint] = await Promise.all([
                this.orm.call("automation.rule", "get_workflow_graph", [[this.resId]]),
                loadJoint(),
            ]);
            this.payload = payload;
            this.joint = joint;
            this.state.countNode = payload.nodes.length;
            this.state.countEdge = payload.edges.length;
            this.state.status = payload.nodes.length ? "ready" : "empty";
        } catch (error) {
            this.state.status = "error";
            this.state.error = error.message || String(error);
            return;
        }
        this.drawToken = (this.drawToken || 0) + 1;
    }

    listen(resId = this.resId) {
        if (!resId || this.listening) {
            return;
        }
        this.listening = `${CHANNEL_PREFIX}${resId}`;
        this.bus.addChannel(this.listening);
        this.bus.subscribe(UPDATE_TYPE, this.onWorkflowUpdate);
    }

    stopListening() {
        if (!this.listening) {
            return;
        }
        this.bus.unsubscribe(UPDATE_TYPE, this.onWorkflowUpdate);
        this.bus.deleteChannel(this.listening);
        this.listening = null;
    }

    teardown() {
        if (this.paper) {
            log("teardown");
        }
        this.paper?.remove();
        this.paper = null;
        this.graph = null;
        this.state.selectedEdgeId = null;
    }

    async draw() {
        const element = this.canvas.el;
        if (!element) {
            this.state.status = "error";
            this.state.error = _t("The canvas element was not mounted.");
            log("draw aborted: no element");
            return;
        }
        log("draw", {
            nodes: this.payload.nodes.length,
            edges: this.payload.edges.length,
            positioned: this.payload.is_positioned,
            runtime: this.payload.runtime_id,
        });
        const { dia, shapes } = this.joint;
        const host = element.ownerDocument.createElement("div");
        element.replaceChildren(host);
        this.graph = new dia.Graph({}, { cellNamespace: shapes });
        this.cellPerNode = new Map();

        for (const node of this.payload.nodes) {
            const cell = new shapes.standard.Rectangle({
                position: { x: node.pos_x, y: node.pos_y },
                size: { width: NODE_WIDTH, height: NODE_HEIGHT },
                attrs: {
                    body: { rx: 6, ry: 6, class: nodeClasses(node), magnet: "passive" },
                    label: {
                        text: shortName(node.name),
                        class: "o_workflow_canvas_label",
                    },
                },
            });
            cell.set("nodeId", node.id);
            this.cellPerNode.set(node.id, cell);
            this.graph.addCell(cell);
        }
        for (const edge of this.payload.edges) {
            this.graph.addCell(this.buildLink(edge));
        }

        this.paper = new dia.Paper({
            el: host,
            model: this.graph,
            width: "100%",
            height: 520,
            gridSize: 10,
            drawGrid: { name: "dot", args: { color: "#d8d8d8" } },
            background: { color: "transparent" },
            cellViewNamespace: shapes,
            linkPinning: false,
            defaultLink: () => new shapes.standard.Link(),
            defaultRouter: { name: "manhattan" },
            defaultConnector: { name: "rounded" },
            interactive: this.isEditable ? { linkMove: false } : false,
            validateConnection: (sourceView, _sm, targetView, _tm, end) =>
                this.isValidConnection(sourceView, targetView, end),
        });

        if (!this.payload.is_positioned) {
            await this.autoLayout({ persist: this.isEditable });
        } else {
            this.fit();
        }
        this.bind();
    }

    bind() {
        if (this.isEditable) {
            const { dia, elementTools } = this.joint;
            for (const cell of this.cellPerNode.values()) {
                this.paper.findViewByModel(cell).addTools(
                    new dia.ToolsView({
                        tools: [new elementTools.HoverConnect()],
                    }),
                );
            }
            log("connect handles attached", this.cellPerNode.size);
        }
        this.paper.on("element:pointerup", (view) => this.saveNodePosition(view));
        this.paper.on("element:pointerdblclick", (view) =>
            this.openAction(view.model.get("nodeId")),
        );
        this.paper.on("link:pointerclick", (view) => this.selectEdge(view.model));
        this.paper.on("link:connect", (view) => this.createEdge(view.model));
        this.paper.on("blank:pointerclick", () => this.selectEdge(null));
    }

    buildLink(edge) {
        const link = new this.joint.shapes.standard.Link({
            source: { id: this.cellPerNode.get(edge.source).id },
            target: { id: this.cellPerNode.get(edge.target).id },
            attrs: {
                line: {
                    class: linkClasses(edge),
                },
            },
            labels: [
                {
                    position: 0.5,
                    attrs: {
                        text: {
                            text: edge.label || conditionLabel(edge.condition),
                            class: "o_workflow_canvas_edge_label",
                        },
                        rect: { class: "o_workflow_canvas_edge_label_bg" },
                    },
                },
            ],
        });
        link.set("edgeId", edge.id);
        return link;
    }

    isValidConnection(sourceView, targetView, end) {
        if (!this.isEditable || end === "source" || !targetView) {
            return false;
        }
        return canConnect(
            this.payload.edges,
            sourceView.model.get("nodeId"),
            targetView.model.get("nodeId"),
        );
    }

    async createEdge(link) {
        const source = link.getSourceCell()?.get("nodeId");
        const target = link.getTargetCell()?.get("nodeId");
        log("connect", { source, target });
        if (!source || !target) {
            log("connect abandoned: an end was not a node");
            return;
        }
        try {
            await this.orm.create("workflow.edge", [
                { source_node_id: source, target_node_id: target },
            ]);
        } catch (error) {
            log("connect refused", error.data?.message || error.message);
            this.notification.add(error.data?.message || error.message, {
                type: "danger",
                title: _t("That connection was refused"),
            });
        }
        await this.load();
    }

    selectEdge(link) {
        this.state.selectedEdgeId = link ? link.get("edgeId") : null;
        for (const cell of this.graph.getLinks()) {
            const view = this.paper.findViewByModel(cell);
            view?.el?.classList?.toggle(
                "o_workflow_canvas_selected",
                cell.get("edgeId") === this.state.selectedEdgeId,
            );
        }
    }

    async removeSelectedEdge() {
        if (!this.state.selectedEdgeId) {
            return;
        }
        await this.orm.unlink("workflow.edge", [this.state.selectedEdgeId]);
        await this.load();
    }

    async saveNodePosition(view) {
        if (!this.isEditable) {
            return;
        }
        const position = view.model.position();
        log("move", view.model.get("nodeId"), position);
        await this.orm.write("ir.actions.server", [view.model.get("nodeId")], {
            pos_x: Math.round(position.x),
            pos_y: Math.round(position.y),
        });
    }

    async autoLayout({ persist } = {}) {
        this.joint.DirectedGraph.layout(this.graph, {
            rankDir: "LR",
            nodeSep: 40,
            edgeSep: 20,
            rankSep: 90,
            marginX: PADDING,
            marginY: PADDING,
        });
        this.fit();
        if (!persist) {
            return;
        }
        await Promise.all(
            [...this.cellPerNode.entries()].map(([nodeId, cell]) => {
                const position = cell.position();
                return this.orm.write("ir.actions.server", [nodeId], {
                    pos_x: Math.round(position.x),
                    pos_y: Math.round(position.y),
                });
            }),
        );
    }

    async relayout() {
        await this.autoLayout({ persist: this.isEditable });
    }

    fit() {
        this.paper.transformToFitContent({
            padding: PADDING,
            maxScale: 1,
            minScale: 0.3,
            verticalAlign: "middle",
            horizontalAlign: "middle",
        });
    }

    openAction(nodeId) {
        if (!nodeId) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "ir.actions.server",
            res_id: nodeId,
            views: [[false, "form"]],
            target: "new",
        });
    }
}

registry.category("view_widgets").add("automation_workflow_canvas", {
    component: WorkflowCanvas,
});
