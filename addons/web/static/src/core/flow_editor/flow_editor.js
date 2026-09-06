// @ts-check
/** @odoo-module native */

import {
    Component,
    onMounted,
    onWillDestroy,
    onWillUpdateProps,
    useExternalListener,
    useRef,
    useState,
} from "@odoo/owl";
import { _t } from "@web/core/translation";

import {
    normalizeConnectionValidation,
    validateConnection,
} from "./connection_validator.js";
import { FlowConnection } from "./flow_connection.js";
import { FlowEditorStore } from "./flow_editor_store.js";
import { FlowNode } from "./flow_node.js";
import { buildConnectionGeometry } from "./geometry/connections.js";
import { clampScale, screenToWorld } from "./geometry/coordinates.js";
import {
    expandRect,
    getNodeRect,
    getNodeSize,
    getObstacleRects,
} from "./geometry/nodes.js";
import { DEFAULT_NODE_HEADER_HEIGHT, getPortAnchor } from "./geometry/ports.js";
import { buildOrthogonalPath } from "./geometry/router.js";

const DEFAULT_NODE_SIZE = { width: 220, height: 120 };
const DEFAULT_MIN_NODE_SIZE = { width: 120, height: 80 };
const DEFAULT_MAX_NODE_SIZE = { width: 640, height: 480 };
const DEFAULT_GRID_SIZE = 20;
const OBSTACLE_PADDING = 20;
/** Pointer travel, in screen pixels, that turns a press into a drag. */
const DRAG_THRESHOLD = 3;

/** Owl's literal-value prop type, so `viewport` accepts an explicit null. */
/** @type {{ value: null }} */
const NULL_VALUE_PROP = { value: null };

/**
 * A pointer gesture can also be cancelled from the keyboard, which carries no
 * pointer of its own and forwards the originating event instead.
 *
 * @typedef {PointerEvent | { pointerId: number | null, originalEvent: Event }} FlowCancelEvent
 */

/**
 * @typedef FlowEditorProps
 * @property {boolean} allowSelfConnections
 * @property {string} ariaLabel
 * @property {(connection: import("./flow_types").FlowConnection) => (boolean | string | import("./connection_validator").FlowConnectionValidation | undefined)} canConnect
 * @property {import("./flow_types").FlowConnection[]} connections
 * @property {number} defaultNodeHeaderHeight
 * @property {import("./flow_types").FlowSize} defaultNodeSize
 * @property {boolean} flagUnreachableNodes mark a node no source node reaches
 * @property {(connection: import("./flow_types").FlowConnection) => string | undefined} getConnectionClass
 * @property {(connection: import("./flow_types").FlowConnection) => string | undefined} getConnectionLabel
 * @property {(node: import("./flow_types").FlowNode) => (typeof Component) | undefined} getNodeComponent
 * @property {number} gridSize
 * @property {import("./flow_types").FlowSize} maxNodeSize
 * @property {import("./flow_types").FlowSize} minNodeSize
 * @property {typeof Component} [NodeComponent]
 * @property {import("./flow_types").FlowNode[]} nodes
 * @property {(connection: import("./flow_types").FlowConnection) => (import("./flow_types").FlowConnection | false | void | Promise<import("./flow_types").FlowConnection | false | void>)} onConnect
 * @property {(params: { connection: import("./flow_types").FlowConnection, validation: import("./connection_validator").FlowConnectionValidation }) => void} onConnectionRejected
 * @property {(params: { connection: import("./flow_types").FlowConnection }) => (boolean | void | Promise<boolean | void>)} onDisconnect
 * @property {(params: { phase: string, node: import("./flow_types").FlowNode | undefined, position: import("./flow_types").FlowPosition, originalEvent: Event }) => void} onDrag
 * @property {(params: { node: import("./flow_types").FlowNode }) => (boolean | void | Promise<boolean | void>)} onNodeDelete
 * @property {(params: import("./flow_node").FlowNodeEventParams) => void} onNodeClick
 * @property {(params: { phase: string }) => void} onPan
 * @property {(params: { phase: string, node: import("./flow_types").FlowNode | undefined, size: import("./flow_types").FlowSize, originalEvent: Event }) => void} onResize
 * @property {(selection: import("./flow_types").FlowSelection) => void} onSelectionChange
 * @property {(viewport: import("./flow_types").FlowViewport) => void} onViewportChange
 * @property {boolean} readonly
 * @property {boolean} showControls
 * @property {import("./flow_types").FlowViewport | null} viewport an explicit
 *  viewport to restore, or null to fit the content once mounted
 */

/**
 * A domain-free node graph: the consumer owns the nodes, the connections and
 * their persistence, and this owns the canvas, the gestures and the routing.
 *
 * @extends {Component<FlowEditorProps>}
 */
export class FlowEditor extends Component {
    static template = "web.FlowEditor";
    static components = { FlowConnection, FlowNode };
    static defaultProps = {
        allowSelfConnections: false,
        canConnect: () => true,
        defaultNodeHeaderHeight: DEFAULT_NODE_HEADER_HEIGHT,
        defaultNodeSize: DEFAULT_NODE_SIZE,
        flagUnreachableNodes: true,
        getConnectionClass: () => "",
        getConnectionLabel: () => "",
        getNodeComponent: /** @type {() => undefined} */ (() => undefined),
        gridSize: DEFAULT_GRID_SIZE,
        maxNodeSize: DEFAULT_MAX_NODE_SIZE,
        minNodeSize: DEFAULT_MIN_NODE_SIZE,
        onConnect: (/** @type {import("./flow_types").FlowConnection} */ connection) =>
            connection,
        onConnectionRejected: () => {},
        onDisconnect: () => true,
        onDrag: () => {},
        onNodeDelete: () => true,
        onNodeClick: () => {},
        onPan: () => {},
        onResize: () => {},
        onSelectionChange: () => {},
        onViewportChange: () => {},
        readonly: false,
        showControls: true,
        viewport: /** @type {import("./flow_types").FlowViewport | null} */ (null),
    };
    static props = {
        allowSelfConnections: {
            type: Boolean,
            optional: true,
        },
        ariaLabel: {
            type: String,
            optional: true,
        },
        canConnect: {
            type: Function,
            optional: true,
        },
        connections: {
            type: Array,
        },
        defaultNodeHeaderHeight: {
            type: Number,
            optional: true,
        },
        defaultNodeSize: {
            type: Object,
            optional: true,
        },
        flagUnreachableNodes: {
            type: Boolean,
            optional: true,
        },
        getConnectionClass: {
            type: Function,
            optional: true,
        },
        getConnectionLabel: {
            type: Function,
            optional: true,
        },
        getNodeComponent: {
            type: Function,
            optional: true,
        },
        gridSize: {
            type: Number,
            optional: true,
        },
        maxNodeSize: {
            type: Object,
            optional: true,
        },
        minNodeSize: {
            type: Object,
            optional: true,
        },
        NodeComponent: {
            type: true,
            optional: true,
        },
        nodes: {
            type: Array,
        },
        onConnect: {
            type: Function,
            optional: true,
        },
        onConnectionRejected: {
            type: Function,
            optional: true,
        },
        onDisconnect: {
            type: Function,
            optional: true,
        },
        onDrag: {
            type: Function,
            optional: true,
        },
        onNodeDelete: {
            type: Function,
            optional: true,
        },
        onNodeClick: {
            type: Function,
            optional: true,
        },
        onPan: {
            type: Function,
            optional: true,
        },
        onResize: {
            type: Function,
            optional: true,
        },
        onSelectionChange: {
            type: Function,
            optional: true,
        },
        onViewportChange: {
            type: Function,
            optional: true,
        },
        readonly: {
            type: Boolean,
            optional: true,
        },
        showControls: {
            type: Boolean,
            optional: true,
        },
        viewport: {
            type: [Object, NULL_VALUE_PROP],
            optional: true,
        },
    };

    /** @type {import("@odoo/owl").Ref<HTMLElement>} */
    canvasRef;
    /** @type {FlowEditorStore} */
    store;
    /** @type {number | null} */
    activePointerId = null;
    /** @type {{ x: number, y: number }} */
    pointerStart = { x: 0, y: 0 };
    /** @type {{ x: number, y: number }} */
    dragOffset = { x: 0, y: 0 };
    /** @type {import("./flow_types").FlowViewport} */
    panOrigin = { x: 0, y: 0, scale: 1 };
    didDrag = false;
    snapNodeDrag = false;
    suppressNodeClick = false;
    /** @type {number | null} */
    viewportAnimationFrame = null;
    /**
     * Resolves to whether the grabbed connection was released by its
     * consumer, once the gesture has moved far enough to ask.
     * @type {Promise<boolean> | null}
     */
    pendingDetach = null;

    setup() {
        this.canvasRef = useRef("canvas");
        this.store = useState(
            new FlowEditorStore({
                nodes: this.props.nodes,
                connections: this.props.connections,
                viewport: this.props.viewport,
                readonly: this.props.readonly,
            }),
        );
        onWillUpdateProps((nextProps) => {
            if (
                nextProps.nodes !== this.props.nodes ||
                nextProps.connections !== this.props.connections
            ) {
                this.store.setGraph({
                    nodes: nextProps.nodes,
                    connections: nextProps.connections,
                });
            }
            if (nextProps.viewport && nextProps.viewport !== this.props.viewport) {
                this.store.setViewport(nextProps.viewport);
            }
            this.store.setReadonly(nextProps.readonly);
        });
        useExternalListener(window, "pointermove", this.onPointerMove);
        useExternalListener(window, "pointerup", this.onPointerUp);
        useExternalListener(window, "pointercancel", this.onPointerCancel);
        useExternalListener(window, "keydown", this.onKeyDown);
        onMounted(() => {
            // No viewport to restore means the consumer has none stored, so the
            // graph is framed rather than left wherever the origin happens to be.
            if (!this.props.viewport) {
                this.fitToContent();
            }
        });
        onWillDestroy(() => this.cancelViewportAnimation());
    }

    /** @returns {HTMLElement | null} */
    get canvasEl() {
        return this.canvasRef.el;
    }

    /**
     * Take the focus for the keyboard shortcuts without scrolling the canvas
     * into view: a scroll here moves the whole graph under a pointer that is
     * already down, and every delta of that gesture is then measured from an
     * origin captured before the jump.
     */
    focusCanvas() {
        this.canvasEl?.focus({ preventScroll: true });
    }

    get ariaLabel() {
        return this.props.ariaLabel || _t("Flow editor");
    }

    get canvasStyle() {
        const { x, y, scale } = this.store.viewport;
        const gridSize = Math.max(this.props.gridSize, 1) * scale;
        return `background-size: ${gridSize}px ${gridSize}px; background-position: ${x}px ${y}px;`;
    }

    get contentStyle() {
        const { x, y, scale } = this.store.viewport;
        return `transform: translate(${x}px, ${y}px) scale(${scale});`;
    }

    get connectionGeometries() {
        const paddedRects = this.store.nodes.map((node) => ({
            id: node.id,
            rect: expandRect(
                getNodeRect(node, this.props.defaultNodeSize),
                OBSTACLE_PADDING,
            ),
        }));
        return this.store.connections
            .map((connection) => {
                const sourceNode = this.store.getNode(connection.sourceNodeId);
                const targetNode = this.store.getNode(connection.targetNodeId);
                if (!sourceNode || !targetNode) {
                    return null;
                }
                return buildConnectionGeometry({
                    connection,
                    sourceNode,
                    targetNode,
                    nodes: this.store.nodes,
                    paddedRects,
                    defaultNodeSize: this.props.defaultNodeSize,
                    defaultNodeHeaderHeight: this.props.defaultNodeHeaderHeight,
                });
            })
            .filter(Boolean);
    }

    /**
     * Geometry for a candidate end already hovering a valid port: delegates
     * to `buildConnectionGeometry`, the exact function a confirmed
     * connection renders with (self-loop shape included), so the preview
     * never has to jump to a different route once the drag is confirmed.
     *
     * @param {Object} candidate
     * @param {import("./flow_types").FlowNodeId} candidate.sourceNodeId
     * @param {import("./flow_types").FlowPortId} candidate.sourcePortId
     * @param {import("./flow_types").FlowNodeId} [candidate.targetNodeId]
     * @param {import("./flow_types").FlowPortId} [candidate.targetPortId]
     * @returns {import("./geometry/connections").FlowConnectionGeometry | null}
     */
    _draftSnappedGeometry({ sourceNodeId, sourcePortId, targetNodeId, targetPortId }) {
        if (targetNodeId === undefined || targetPortId === undefined) {
            return null;
        }
        const sourceNode = this.store.getNode(sourceNodeId);
        const targetNode = this.store.getNode(targetNodeId);
        if (!sourceNode || !targetNode) {
            return null;
        }
        return buildConnectionGeometry({
            connection: {
                id: "flow-connection-draft",
                sourceNodeId,
                sourcePortId,
                targetNodeId,
                targetPortId,
            },
            sourceNode,
            targetNode,
            nodes: this.store.nodes,
            defaultNodeSize: this.props.defaultNodeSize,
            defaultNodeHeaderHeight: this.props.defaultNodeHeaderHeight,
        });
    }

    get draftConnectionGeometry() {
        const interaction = this.store.interaction;
        if (interaction?.type !== "connection_drag") {
            return null;
        }
        const draft = interaction.connectionDraft;
        if (draft.pendingConnectionId !== undefined) {
            return null;
        }
        return draft.reconnectSource
            ? this._reconnectDraftGeometry(draft)
            : this._forwardDraftGeometry(draft);
    }

    /**
     * The end being dragged is the SOURCE: the target stays anchored to its
     * port and the free end follows the pointer.
     *
     * @param {import("./flow_types").FlowConnectionDraft} draft
     * @returns {import("./geometry/connections").FlowConnectionGeometry | null}
     */
    _reconnectDraftGeometry(draft) {
        const snapped =
            draft.sourceCandidateNodeId !== undefined &&
            draft.sourceCandidatePortId !== undefined
                ? this._draftSnappedGeometry({
                      sourceNodeId: draft.sourceCandidateNodeId,
                      sourcePortId: draft.sourceCandidatePortId,
                      targetNodeId: draft.targetNodeId,
                      targetPortId: draft.targetPortId,
                  })
                : null;
        if (snapped) {
            return snapped;
        }
        const targetNode =
            draft.targetNodeId === undefined
                ? undefined
                : this.store.getNode(draft.targetNodeId);
        const end =
            targetNode && draft.targetPortId !== undefined
                ? getPortAnchor(
                      targetNode,
                      draft.targetPortId,
                      this.props.defaultNodeSize,
                      this.props.defaultNodeHeaderHeight,
                  )
                : null;
        if (!end) {
            return null;
        }
        return {
            id: "flow-connection-draft",
            ...buildOrthogonalPath({
                start: draft.pointer,
                end,
                obstacles: this._draftObstacles(draft.targetNodeId),
            }),
        };
    }

    /**
     * The end being dragged is the TARGET, leaving the source port anchored.
     *
     * @param {import("./flow_types").FlowConnectionDraft} draft
     * @returns {import("./geometry/connections").FlowConnectionGeometry | null}
     */
    _forwardDraftGeometry(draft) {
        const { sourceNodeId, sourcePortId, pointer } = draft;
        const snapped =
            draft.targetNodeId === undefined
                ? null
                : this._draftSnappedGeometry({
                      sourceNodeId,
                      sourcePortId,
                      targetNodeId: draft.targetNodeId,
                      targetPortId: draft.targetPortId,
                  });
        if (snapped) {
            return snapped;
        }
        const sourceNode = this.store.getNode(sourceNodeId);
        const start =
            sourceNode &&
            getPortAnchor(
                sourceNode,
                sourcePortId,
                this.props.defaultNodeSize,
                this.props.defaultNodeHeaderHeight,
            );
        if (!start) {
            return null;
        }
        return {
            id: "flow-connection-draft",
            ...buildOrthogonalPath({
                start,
                end: pointer,
                obstacles: this._draftObstacles(sourceNodeId),
            }),
        };
    }

    /**
     * Every node but the one the dragged end is anchored to: an anchor sitting
     * on its own node's boundary would read as blocked from the first segment.
     *
     * @param {import("./flow_types").FlowNodeId} [anchoredNodeId]
     * @returns {import("./geometry/nodes").FlowRect[]}
     */
    _draftObstacles(anchoredNodeId) {
        return getObstacleRects(this.store.nodes, {
            defaultSize: this.props.defaultNodeSize,
            padding: OBSTACLE_PADDING,
            excludedNodeIds: new Set(
                anchoredNodeId === undefined ? [] : [anchoredNodeId],
            ),
        });
    }

    /**
     * @param {import("./flow_types").FlowConnectionId} connectionId
     * @returns {string}
     */
    getConnectionClass(connectionId) {
        const connection = this.store.getConnection(connectionId);
        return (connection && this.props.getConnectionClass(connection)) || "";
    }

    /**
     * @param {import("./flow_types").FlowConnectionId} connectionId
     * @returns {string}
     */
    getConnectionLabel(connectionId) {
        const connection = this.store.getConnection(connectionId);
        return (connection && this.props.getConnectionLabel(connection)) || "";
    }

    get isInteracting() {
        return Boolean(this.store.interaction);
    }

    get emptyLabel() {
        return _t("No nodes");
    }

    get fitLabel() {
        return _t("Fit to content");
    }

    get zoomInLabel() {
        return _t("Zoom in");
    }

    get zoomOutLabel() {
        return _t("Zoom out");
    }

    get flowLocationLabel() {
        return _t("Return to the flow");
    }

    get flowBounds() {
        if (!this.store.nodes.length) {
            return null;
        }
        const rects = this.store.nodes.map((node) =>
            getNodeRect(node, this.props.defaultNodeSize),
        );
        return {
            x1: Math.min(...rects.map((rect) => rect.x1)),
            y1: Math.min(...rects.map((rect) => rect.y1)),
            x2: Math.max(...rects.map((rect) => rect.x2)),
            y2: Math.max(...rects.map((rect) => rect.y2)),
        };
    }

    get flowCenter() {
        if (!this.store.nodes.length) {
            return null;
        }
        const centers = this.store.nodes.map((node) => {
            const rect = getNodeRect(node, this.props.defaultNodeSize);
            return {
                x: (rect.x1 + rect.x2) / 2,
                y: (rect.y1 + rect.y2) / 2,
            };
        });
        return {
            x: centers.reduce((sum, center) => sum + center.x, 0) / centers.length,
            y: centers.reduce((sum, center) => sum + center.y, 0) / centers.length,
        };
    }

    /**
     * Every node a source node reaches, a source node being one with no input
     * port at all. A graph whose every node accepts an input therefore has no
     * source and reports nothing connected, which is why a consumer whose
     * domain has no single entry point turns the flag off rather than reading
     * this as a graph full of unreachable nodes.
     */
    get connectedNodeIds() {
        const connectedNodeIds = new Set(
            this.store.nodes.filter((node) => !node.input).map((node) => node.id),
        );
        let previousSize;
        do {
            previousSize = connectedNodeIds.size;
            for (const connection of this.store.connections) {
                if (connectedNodeIds.has(connection.sourceNodeId)) {
                    connectedNodeIds.add(connection.targetNodeId);
                }
            }
        } while (connectedNodeIds.size !== previousSize);
        return connectedNodeIds;
    }

    get flowLocationIndicator() {
        const canvasEl = this.canvasEl;
        const target = this.flowCenter;
        if (!canvasEl || !target) {
            return null;
        }
        const canvasRect = canvasEl.getBoundingClientRect();
        const { x, y, scale } = this.store.viewport;
        const view = {
            x1: -x / scale,
            y1: -y / scale,
            x2: (canvasRect.width - x) / scale,
            y2: (canvasRect.height - y) / scale,
        };
        const hasVisibleNode = this.store.nodes.some((node) => {
            const rect = getNodeRect(node, this.props.defaultNodeSize);
            return (
                rect.x2 >= view.x1 &&
                rect.x1 <= view.x2 &&
                rect.y2 >= view.y1 &&
                rect.y1 <= view.y2
            );
        });
        if (hasVisibleNode) {
            return null;
        }
        const viewCenter = {
            x: (view.x1 + view.x2) / 2,
            y: (view.y1 + view.y2) / 2,
        };
        const angle =
            (Math.atan2(target.y - viewCenter.y, target.x - viewCenter.x) * 180) /
                Math.PI +
            45;
        return {
            angle,
            x: canvasRect.width / 2,
            y: canvasRect.height / 2,
        };
    }

    get flowLocationIndicatorStyle() {
        const indicator = this.flowLocationIndicator;
        return indicator
            ? `left: ${indicator.x}px; top: ${indicator.y}px; transform: translate(-50%, -50%) rotate(${indicator.angle}deg);`
            : "";
    }

    /**
     * @param {import("./flow_types").FlowNodeId} nodeId
     * @param {import("./flow_types").FlowPortId} portId
     * @returns {"valid" | "invalid" | undefined}
     */
    getPortValidation(nodeId, portId) {
        const interaction = this.store.interaction;
        const draft =
            interaction?.type === "connection_drag"
                ? interaction.connectionDraft
                : undefined;
        if (!draft) {
            return;
        }
        if (draft.reconnectSource) {
            if (
                draft.sourceCandidateNodeId !== nodeId ||
                draft.sourceCandidatePortId !== portId
            ) {
                return;
            }
            if (draft.targetNodeId === undefined || draft.targetPortId === undefined) {
                return "invalid";
            }
            return this.validateConnectionCandidate({
                id: "flow-connection-draft",
                sourceNodeId: nodeId,
                sourcePortId: portId,
                targetNodeId: draft.targetNodeId,
                targetPortId: draft.targetPortId,
            }).valid
                ? "valid"
                : "invalid";
        }
        if (draft.targetNodeId !== nodeId || draft.targetPortId !== portId) {
            return;
        }
        return this.validateConnectionCandidate({
            id: "flow-connection-draft",
            sourceNodeId: draft.sourceNodeId,
            sourcePortId: draft.sourcePortId,
            targetNodeId: nodeId,
            targetPortId: portId,
        }).valid
            ? "valid"
            : "invalid";
    }

    /**
     * @param {{ clientX: number, clientY: number }} ev
     * @returns {import("./flow_types").FlowPosition}
     */
    toWorld(ev) {
        const canvasRect = this.canvasEl?.getBoundingClientRect() ?? {
            left: 0,
            top: 0,
        };
        return screenToWorld(
            { x: ev.clientX, y: ev.clientY },
            canvasRect,
            this.store.viewport,
        );
    }

    /**
     * @param {PointerEvent} ev
     */
    onCanvasPointerDown(ev) {
        const target = /** @type {HTMLElement | null} */ (ev.target);
        if (
            (ev.button !== 0 && ev.button !== 1) ||
            target?.closest(
                ".o_flow_editor_node, .o_flow_editor_connection, .o_flow_editor_controls, .o_flow_editor_location_indicator",
            )
        ) {
            return;
        }
        ev.preventDefault();
        this.cancelViewportAnimation();
        this.focusCanvas();
        this.clearSelection();
        if (!this.store.startInteraction({ type: "pan" })) {
            return;
        }
        this.activePointerId = ev.pointerId;
        this.pointerStart = { x: ev.clientX, y: ev.clientY };
        this.panOrigin = { ...this.store.viewport };
        this.props.onPan({ phase: "start" });
    }

    /**
     * @param {import("./flow_node").FlowNodeEventParams} params
     */
    onNodePointerDown({ node, originalEvent }) {
        const pointerEvent = /** @type {PointerEvent} */ (originalEvent);
        if (pointerEvent.button !== 0) {
            return;
        }
        pointerEvent.preventDefault();
        pointerEvent.stopPropagation();
        this.focusCanvas();
        const pointer = this.toWorld(pointerEvent);
        if (
            !this.store.startInteraction({
                type: "node_drag",
                nodeId: node.id,
                origin: { ...node.position },
            })
        ) {
            return;
        }
        this.selectNode(node.id);
        this.activePointerId = pointerEvent.pointerId;
        this.pointerStart = { x: pointerEvent.clientX, y: pointerEvent.clientY };
        this.dragOffset = {
            x: pointer.x - node.position.x,
            y: pointer.y - node.position.y,
        };
        this.snapNodeDrag = pointerEvent.altKey;
        this.didDrag = false;
        this.props.onDrag({
            phase: "start",
            node,
            position: { ...node.position },
            originalEvent: pointerEvent,
        });
    }

    /**
     * @param {import("./flow_port").FlowPortPointerDownParams} params
     */
    async onPortPointerDown({ nodeId, port, originalEvent }) {
        if (
            originalEvent.button !== 0 ||
            this.store.readonly ||
            this.store.interaction
        ) {
            return;
        }
        originalEvent.preventDefault();
        this.focusCanvas();
        let sourceNodeId = nodeId;
        let sourcePortId = port.id;
        let connection;
        let reconnectSource = false;
        let targetNodeId;
        let targetPortId;
        if (port.direction === "input") {
            connection = this.lastConnectionAt(
                (candidate) =>
                    candidate.targetNodeId === nodeId &&
                    candidate.targetPortId === port.id,
            );
            if (connection) {
                sourceNodeId = connection.sourceNodeId;
                sourcePortId = connection.sourcePortId;
            } else {
                reconnectSource = true;
                targetNodeId = nodeId;
                targetPortId = port.id;
            }
        } else {
            connection = this.lastConnectionAt(
                (candidate) =>
                    candidate.sourceNodeId === nodeId &&
                    candidate.sourcePortId === port.id,
            );
            if (connection) {
                reconnectSource = true;
                targetNodeId = connection.targetNodeId;
                targetPortId = connection.targetPortId;
            }
        }
        const pointer = this.toWorld(originalEvent);
        if (
            !this.store.startInteraction({
                type: "connection_drag",
                connectionDraft: {
                    sourceNodeId,
                    sourcePortId,
                    pointer,
                    ...(reconnectSource
                        ? {
                              reconnectSource: true,
                              targetNodeId,
                              targetPortId,
                          }
                        : {}),
                    // A connection is grabbed, not dropped: it stays until the
                    // pointer has travelled DRAG_THRESHOLD, so a click on a
                    // port is not a deletion (the automation canvas unlinks
                    // the edge server-side in onDisconnect).
                    ...(connection ? { pendingConnectionId: connection.id } : {}),
                },
            })
        ) {
            return;
        }
        this.activePointerId = originalEvent.pointerId;
        this.pointerStart = { x: originalEvent.clientX, y: originalEvent.clientY };
    }

    /**
     * Ask the consumer to release the grabbed connection and take it out of
     * the store when it agrees; a veto ends the gesture where it stands.
     *
     * @param {import("./flow_types").FlowConnectionDraft} draft
     * @returns {Promise<boolean>}
     */
    async detachPendingConnection(draft) {
        const connectionId = draft.pendingConnectionId;
        delete draft.pendingConnectionId;
        const connection =
            connectionId === undefined
                ? undefined
                : this.store.getConnection(connectionId);
        if (!connection) {
            return true;
        }
        if ((await this.props.onDisconnect({ connection })) === false) {
            const interaction = this.store.interaction;
            if (
                interaction?.type === "connection_drag" &&
                interaction.connectionDraft === draft
            ) {
                this.store.cancelInteraction();
                this.resetPointerState();
            }
            return false;
        }
        this.store.removeConnection(connection.id);
        return true;
    }

    /**
     * The most recently added connection wins when a port holds several: ids
     * are compared numerically so `flow-connection-10` sorts after `-9`.
     *
     * @param {(connection: import("./flow_types").FlowConnection) => boolean} predicate
     * @returns {import("./flow_types").FlowConnection | undefined}
     */
    lastConnectionAt(predicate) {
        return this.store.connections
            .filter(predicate)
            .sort((connectionA, connectionB) =>
                String(connectionA.id).localeCompare(
                    String(connectionB.id),
                    undefined,
                    {
                        numeric: true,
                    },
                ),
            )
            .at(-1);
    }

    /**
     * @param {import("./flow_node").FlowNodeEventParams} params
     */
    onResizePointerDown({ node, originalEvent }) {
        const pointerEvent = /** @type {PointerEvent} */ (originalEvent);
        if (
            pointerEvent.button !== 0 ||
            node.shape === "circle" ||
            node.resizable === false
        ) {
            return;
        }
        pointerEvent.preventDefault();
        this.focusCanvas();
        const size = getNodeSize(node, this.props.defaultNodeSize);
        if (
            !this.store.startInteraction({
                type: "node_resize",
                nodeId: node.id,
                origin: { ...size },
            })
        ) {
            return;
        }
        this.selectNode(node.id);
        this.activePointerId = pointerEvent.pointerId;
        this.pointerStart = { x: pointerEvent.clientX, y: pointerEvent.clientY };
        this.props.onResize({
            phase: "start",
            node,
            size: { ...size },
            originalEvent: pointerEvent,
        });
    }

    /**
     * @param {PointerEvent} ev
     */
    onPointerMove(ev) {
        const interaction = this.store.interaction;
        if (ev.pointerId !== this.activePointerId || !interaction) {
            return;
        }
        ev.preventDefault();
        if (interaction.type === "node_drag") {
            const pointer = this.toWorld(ev);
            const position = {
                x: pointer.x - this.dragOffset.x,
                y: pointer.y - this.dragOffset.y,
            };
            if (this.snapNodeDrag) {
                const gridSize = Math.max(this.props.gridSize, 1);
                position.x = Math.round(position.x / gridSize) * gridSize;
                position.y = Math.round(position.y / gridSize) * gridSize;
            }
            this.didDrag ||=
                Math.hypot(
                    ev.clientX - this.pointerStart.x,
                    ev.clientY - this.pointerStart.y,
                ) > 3;
            if (this.store.moveNode(interaction.nodeId, position)) {
                this.props.onDrag({
                    phase: "move",
                    node: this.store.getNode(interaction.nodeId),
                    position,
                    originalEvent: ev,
                });
            }
        } else if (interaction.type === "node_resize") {
            const { nodeId, origin } = interaction;
            const scale = this.store.viewport.scale;
            const size = {
                width: this.clampNodeSide(
                    "width",
                    origin.width + (ev.clientX - this.pointerStart.x) / scale,
                ),
                height: this.clampNodeSide(
                    "height",
                    origin.height + (ev.clientY - this.pointerStart.y) / scale,
                ),
            };
            if (this.store.resizeNode(nodeId, size)) {
                this.props.onResize({
                    phase: "move",
                    node: this.store.getNode(nodeId),
                    size,
                    originalEvent: ev,
                });
            }
        } else if (interaction.type === "connection_drag") {
            const draft = interaction.connectionDraft;
            if (draft.pendingConnectionId !== undefined) {
                const travelled = Math.hypot(
                    ev.clientX - this.pointerStart.x,
                    ev.clientY - this.pointerStart.y,
                );
                if (travelled <= DRAG_THRESHOLD) {
                    return;
                }
                this.pendingDetach ??= this.detachPendingConnection(draft);
            }
            const target = interaction.connectionDraft.reconnectSource
                ? this.getOutputPortAtPoint(ev.clientX, ev.clientY)
                : this.getInputPortAtPoint(ev.clientX, ev.clientY);
            this.store.updateConnectionDraft(
                this.toWorld(ev),
                target
                    ? {
                          nodeId: target.node.id,
                          portId: target.portId,
                      }
                    : undefined,
            );
        } else {
            this.setViewport({
                x: this.panOrigin.x + ev.clientX - this.pointerStart.x,
                y: this.panOrigin.y + ev.clientY - this.pointerStart.y,
            });
        }
    }

    /**
     * @param {"width" | "height"} side
     * @param {number} value
     * @returns {number}
     */
    clampNodeSide(side, value) {
        return Math.min(
            this.props.maxNodeSize[side],
            Math.max(this.props.minNodeSize[side], value),
        );
    }

    /**
     * @param {PointerEvent} ev
     */
    async onPointerUp(ev) {
        const interaction = this.store.interaction;
        if (ev.pointerId !== this.activePointerId || !interaction) {
            return;
        }
        if (interaction.type === "node_drag") {
            const node = this.store.getNode(interaction.nodeId);
            this.props.onDrag({
                phase: "end",
                node,
                position: { ...(node?.position ?? interaction.origin) },
                originalEvent: ev,
            });
            this.suppressNodeClick = this.didDrag;
            this.store.endInteraction();
        } else if (interaction.type === "node_resize") {
            const node = this.store.getNode(interaction.nodeId);
            this.props.onResize({
                phase: "end",
                node,
                size: node
                    ? getNodeSize(node, this.props.defaultNodeSize)
                    : interaction.origin,
                originalEvent: ev,
            });
            this.store.endInteraction();
        } else if (interaction.type === "connection_drag") {
            // A self-connection's source and target ports share the same
            // node <article>, so the browser's own click-target resolution
            // (nearest common ancestor of pointerdown/pointerup) synthesizes
            // a click on that node once released - the ports' own click
            // handlers stop propagation, but aren't in that click's path.
            // Connecting two different nodes never hits this: their common
            // ancestor sits above any element with a click handler.
            this.suppressNodeClick = true;
            const draft = interaction.connectionDraft;
            try {
                const detached = this.pendingDetach
                    ? await this.pendingDetach
                    : draft.pendingConnectionId === undefined;
                if (detached && this.store.interaction === interaction) {
                    await this.connectToPortAtPointer(draft, ev);
                }
            } finally {
                this.pendingDetach = null;
                if (this.store.interaction === interaction) {
                    this.store.endInteraction();
                }
                this.resetPointerState();
            }
            return;
        } else {
            this.store.endInteraction();
            if (interaction.type === "pan") {
                this.props.onPan({ phase: "end" });
            }
        }
        this.resetPointerState();
    }

    /**
     * @param {FlowCancelEvent} ev
     */
    onPointerCancel(ev) {
        const interaction = this.store.interaction;
        if (ev.pointerId !== this.activePointerId || !interaction) {
            return;
        }
        const originalEvent = "originalEvent" in ev ? ev.originalEvent : ev;
        this.pendingDetach = null;
        this.store.cancelInteraction();
        if (interaction.type === "node_drag") {
            this.props.onDrag({
                phase: "cancel",
                node: this.store.getNode(interaction.nodeId),
                position: { ...interaction.origin },
                originalEvent,
            });
        } else if (interaction.type === "node_resize") {
            this.props.onResize({
                phase: "cancel",
                node: this.store.getNode(interaction.nodeId),
                size: { ...interaction.origin },
                originalEvent,
            });
        } else if (interaction.type === "pan") {
            this.props.onPan({ phase: "cancel" });
        }
        this.resetPointerState();
    }

    /**
     * @param {import("./flow_types").FlowConnectionDraft} draft
     * @param {PointerEvent} ev
     */
    async connectToPortAtPointer(draft, ev) {
        if (draft.reconnectSource) {
            const source = this.getOutputPortAtPoint(ev.clientX, ev.clientY);
            const targetNode =
                draft.targetNodeId === undefined
                    ? undefined
                    : this.store.getNode(draft.targetNodeId);
            if (source && targetNode && draft.targetPortId !== undefined) {
                await this.connectPorts(
                    {
                        sourceNodeId: source.node.id,
                        sourcePortId: source.portId,
                    },
                    {
                        node: targetNode,
                        portId: draft.targetPortId,
                    },
                );
            }
            return;
        }
        const target = this.getInputPortAtPoint(ev.clientX, ev.clientY);
        if (!target) {
            return;
        }
        await this.connectPorts(draft, target);
    }

    /**
     * @param {{ sourceNodeId: import("./flow_types").FlowNodeId, sourcePortId: import("./flow_types").FlowPortId }} draft
     * @param {{ node: import("./flow_types").FlowNode, portId: import("./flow_types").FlowPortId }} target
     */
    async connectPorts(draft, target) {
        const connection = {
            id: this.store.getNextConnectionId(),
            sourceNodeId: draft.sourceNodeId,
            sourcePortId: draft.sourcePortId,
            targetNodeId: target.node.id,
            targetPortId: target.portId,
        };
        const validation = this.validateConnectionCandidate(connection);
        if (!validation.valid) {
            this.props.onConnectionRejected({ connection, validation });
            return;
        }
        const result = await this.props.onConnect(connection);
        if (result !== false) {
            const persistedConnection =
                result && typeof result === "object" ? result : connection;
            const persistedValidation =
                this.validateConnectionCandidate(persistedConnection);
            if (persistedValidation.valid) {
                this.store.addConnection(persistedConnection);
            } else {
                this.props.onConnectionRejected({
                    connection: persistedConnection,
                    validation: persistedValidation,
                });
            }
        }
    }

    /**
     * The port of the given direction under a screen point, if it belongs to
     * this canvas and the node it is drawn on really declares it.
     *
     * @param {number} clientX
     * @param {number} clientY
     * @param {import("./flow_types").FlowPortDirection} direction
     * @returns {{ node: import("./flow_types").FlowNode, portId: import("./flow_types").FlowPortId } | null}
     */
    getPortAtPoint(clientX, clientY, direction) {
        const portEl = document
            .elementFromPoint(clientX, clientY)
            ?.closest(`.o_flow_editor_port_${direction}`);
        if (!portEl || !this.canvasEl?.contains(portEl)) {
            return null;
        }
        const { nodeId, portId } = /** @type {HTMLElement} */ (portEl).dataset;
        if (portId === undefined) {
            return null;
        }
        const node = this.store.nodes.find(
            (candidate) => String(candidate.id) === nodeId,
        );
        const declared =
            direction === "input"
                ? node?.input?.id === portId
                : node?.outputs.some((output) => output.id === portId);
        return node && declared ? { node, portId } : null;
    }

    /**
     * @param {number} clientX
     * @param {number} clientY
     */
    getInputPortAtPoint(clientX, clientY) {
        return this.getPortAtPoint(clientX, clientY, "input");
    }

    /**
     * @param {number} clientX
     * @param {number} clientY
     */
    getOutputPortAtPoint(clientX, clientY) {
        return this.getPortAtPoint(clientX, clientY, "output");
    }

    /**
     * Apply structural rules before delegating domain-specific rules.
     *
     * `canConnect` must be synchronous because it also drives hover feedback.
     *
     * @param {import("./flow_types").FlowConnection} connection
     * @returns {import("./connection_validator").FlowConnectionValidation}
     */
    validateConnectionCandidate(connection) {
        const validation = validateConnection(connection, {
            nodes: this.store.nodes,
            connections: this.store.connections,
            allowSelfConnections: this.props.allowSelfConnections,
        });
        if (!validation.valid) {
            return validation;
        }
        return normalizeConnectionValidation(this.props.canConnect(connection));
    }

    /**
     * @param {WheelEvent} ev
     */
    onWheel(ev) {
        const canvasEl = this.canvasEl;
        if ((!ev.ctrlKey && !ev.metaKey) || !canvasEl) {
            return;
        }
        ev.preventDefault();
        this.cancelViewportAnimation();
        const canvasRect = canvasEl.getBoundingClientRect();
        const pointer = screenToWorld(
            { x: ev.clientX, y: ev.clientY },
            canvasRect,
            this.store.viewport,
        );
        const scale = clampScale(
            this.store.viewport.scale * (ev.deltaY > 0 ? 0.9 : 1.1),
        );
        this.setViewport({
            x: ev.clientX - canvasRect.left - pointer.x * scale,
            y: ev.clientY - canvasRect.top - pointer.y * scale,
            scale,
        });
    }

    /**
     * @param {number} factor
     */
    zoomBy(factor) {
        const canvasEl = this.canvasEl;
        if (!canvasEl) {
            return;
        }
        this.cancelViewportAnimation();
        const canvasRect = canvasEl.getBoundingClientRect();
        const center = {
            x: canvasRect.left + canvasRect.width / 2,
            y: canvasRect.top + canvasRect.height / 2,
        };
        const worldCenter = screenToWorld(center, canvasRect, this.store.viewport);
        const scale = clampScale(this.store.viewport.scale * factor);
        this.setViewport({
            x: canvasRect.width / 2 - worldCenter.x * scale,
            y: canvasRect.height / 2 - worldCenter.y * scale,
            scale,
        });
    }

    zoomIn() {
        this.zoomBy(1.1);
    }

    zoomOut() {
        this.zoomBy(0.9);
    }

    fitToContent() {
        const canvasEl = this.canvasEl;
        if (!canvasEl) {
            return;
        }
        this.cancelViewportAnimation();
        const canvasRect = canvasEl.getBoundingClientRect();
        const bounds = this.flowBounds;
        if (!bounds || !canvasRect.width || !canvasRect.height) {
            this.setViewport({ x: 0, y: 0, scale: 1 });
            return;
        }
        const padding = 48;
        const width = Math.max(bounds.x2 - bounds.x1, 1);
        const height = Math.max(bounds.y2 - bounds.y1, 1);
        const scale = clampScale(
            Math.min(
                (canvasRect.width - padding * 2) / width,
                (canvasRect.height - padding * 2) / height,
                1,
            ),
        );
        this.setViewport({
            x: (canvasRect.width - width * scale) / 2 - bounds.x1 * scale,
            y: (canvasRect.height - height * scale) / 2 - bounds.y1 * scale,
            scale,
        });
    }

    /**
     * @param {MouseEvent} ev
     */
    onFlowLocationClick(ev) {
        ev.stopPropagation();
        const target = this.flowCenter;
        const canvasEl = this.canvasEl;
        if (!target || !canvasEl) {
            return;
        }
        const canvasRect = canvasEl.getBoundingClientRect();
        const scale = this.store.viewport.scale;
        this.animateViewportTo({
            x: canvasRect.width / 2 - target.x * scale,
            y: canvasRect.height / 2 - target.y * scale,
        });
    }

    /**
     * Animate viewport translation so the directional indicator has a clear outcome.
     *
     * @param {{ x: number, y: number }} target
     * @param {number} [duration]
     */
    animateViewportTo(target, duration = 400) {
        this.cancelViewportAnimation();
        const start = { ...this.store.viewport };
        const delta = {
            x: target.x - start.x,
            y: target.y - start.y,
        };
        /** @type {number | undefined} */
        let startTime;
        /** @param {number} timestamp */
        const step = (timestamp) => {
            startTime ??= timestamp;
            const progress = Math.min(1, (timestamp - startTime) / duration);
            const eased =
                progress < 0.5 ? 2 * progress ** 2 : 1 - (-2 * progress + 2) ** 2 / 2;
            this.setViewport({
                x: start.x + delta.x * eased,
                y: start.y + delta.y * eased,
            });
            if (progress < 1) {
                this.viewportAnimationFrame = requestAnimationFrame(step);
            } else {
                this.viewportAnimationFrame = null;
            }
        };
        this.viewportAnimationFrame = requestAnimationFrame(step);
    }

    cancelViewportAnimation() {
        if (this.viewportAnimationFrame) {
            cancelAnimationFrame(this.viewportAnimationFrame);
            this.viewportAnimationFrame = null;
        }
    }

    /**
     * @param {Partial<import("./flow_types").FlowViewport>} values
     */
    setViewport(values) {
        this.store.setViewport(values);
        this.props.onViewportChange({ ...this.store.viewport });
    }

    /**
     * @param {import("./flow_node").FlowNodeEventParams} params
     */
    onNodeClick({ node, originalEvent }) {
        if (this.suppressNodeClick) {
            this.suppressNodeClick = false;
            return;
        }
        this.selectNode(node.id);
        this.props.onNodeClick({ node, originalEvent });
    }

    /**
     * @param {import("./flow_connection").FlowConnectionClickParams} params
     */
    onConnectionClick({ connectionId }) {
        this.focusCanvas();
        this.store.setSelection({ connectionIds: [connectionId] });
        this.notifySelectionChange();
    }

    /**
     * @param {import("./flow_types").FlowNodeId} nodeId
     */
    selectNode(nodeId) {
        this.store.setSelection({ nodeIds: [nodeId] });
        this.notifySelectionChange();
    }

    clearSelection() {
        this.store.clearSelection();
        this.notifySelectionChange();
    }

    notifySelectionChange() {
        this.props.onSelectionChange({
            nodeIds: [...this.store.selection.nodeIds],
            connectionIds: [...this.store.selection.connectionIds],
        });
    }

    /**
     * @param {{ node: import("./flow_types").FlowNode }} params
     */
    async onNodeDeleteClick({ node }) {
        if (await this.deleteNode(node)) {
            this.notifySelectionChange();
        }
    }

    /**
     * @param {import("./flow_types").FlowNode | undefined} node
     * @returns {Promise<boolean>}
     */
    async deleteNode(node) {
        if (
            !node ||
            node.readonly ||
            node.deletable === false ||
            (await this.props.onNodeDelete({ node })) === false
        ) {
            return false;
        }
        const attachedConnections = this.store.connections.filter(
            (connection) =>
                connection.sourceNodeId === node.id ||
                connection.targetNodeId === node.id,
        );
        for (const connection of attachedConnections) {
            if ((await this.props.onDisconnect({ connection })) === false) {
                return false;
            }
        }
        return this.store.removeNode(node.id);
    }

    /**
     * @param {KeyboardEvent} ev
     */
    async onKeyDown(ev) {
        if (!this.canvasEl?.contains(document.activeElement)) {
            return;
        }
        if (ev.key === "Escape" && this.store.interaction) {
            ev.preventDefault();
            this.onPointerCancel({
                pointerId: this.activePointerId,
                originalEvent: ev,
            });
            return;
        }
        const activeTag = document.activeElement?.tagName;
        if (
            this.store.readonly ||
            (ev.key !== "Delete" && ev.key !== "Backspace") ||
            (activeTag !== undefined && ["INPUT", "TEXTAREA"].includes(activeTag))
        ) {
            return;
        }
        ev.preventDefault();
        for (const connectionId of [...this.store.selection.connectionIds]) {
            const connection = this.store.getConnection(connectionId);
            if (
                connection &&
                (await this.props.onDisconnect({ connection })) !== false
            ) {
                this.store.removeConnection(connectionId);
            }
        }
        for (const nodeId of [...this.store.selection.nodeIds]) {
            const node = this.store.getNode(nodeId);
            await this.deleteNode(node);
        }
        this.notifySelectionChange();
    }

    resetPointerState() {
        this.activePointerId = null;
        this.pointerStart = { x: 0, y: 0 };
        this.panOrigin = { x: 0, y: 0, scale: 1 };
        this.dragOffset = { x: 0, y: 0 };
        this.didDrag = false;
        this.snapNodeDrag = false;
    }

    /**
     * @param {import("./flow_types").FlowNodeId} nodeId
     * @returns {boolean}
     */
    isNodeSelected(nodeId) {
        return this.store.selection.nodeIds.includes(nodeId);
    }

    /**
     * @param {import("./flow_types").FlowConnectionId} connectionId
     * @returns {boolean}
     */
    isConnectionSelected(connectionId) {
        return this.store.selection.connectionIds.includes(connectionId);
    }
}
