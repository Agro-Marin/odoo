// @ts-check
/** @odoo-module native */

/** @typedef {string | number} FlowNodeId */

/** @typedef {string | number} FlowConnectionId */

/** @typedef {string} FlowPortId */

/**
 * @typedef FlowPosition
 * @property {number} x
 * @property {number} y
 */

/**
 * @typedef FlowSize
 * @property {number} width
 * @property {number} height
 */

/**
 * @typedef FlowViewport
 * @property {number} x
 * @property {number} y
 * @property {number} scale
 */

/**
 * @typedef FlowRecord
 * @property {string} resModel
 * @property {number} resId
 * @property {Record<string, any>} [data]
 */

/** @typedef {"input" | "output"} FlowPortDirection */

/**
 * @typedef FlowPort
 * @property {FlowPortId} id
 * @property {FlowPortDirection} direction
 * @property {string} [label]
 * @property {string[]} [accepts]
 * @property {string} [provides]
 * @property {number} [maxConnections]
 * @property {Record<string, any>} [data]
 */

/**
 * @typedef FlowNode
 * @property {FlowNodeId} id
 * @property {string} type
 * @property {FlowPosition} position
 * @property {FlowSize} [size]
 * @property {"rectangle" | "circle"} [shape]
 * @property {number} [headerHeight]
 * @property {FlowRecord} [record]
 * @property {FlowPort} [input]
 * @property {FlowPort[]} outputs
 * @property {Record<string, any>} [data]
 * @property {boolean} [readonly]
 * @property {boolean} [deletable]
 * @property {boolean} [resizable]
 */

/**
 * @typedef FlowSelection
 * @property {FlowNodeId[]} nodeIds
 * @property {FlowConnectionId[]} connectionIds
 */

/**
 * @typedef FlowConnectionDraft
 * @property {FlowNodeId} sourceNodeId
 * @property {FlowPortId} sourcePortId
 * @property {FlowPosition} pointer
 * @property {boolean} [reconnectSource]
 * @property {FlowNodeId} [sourceCandidateNodeId]
 * @property {FlowPortId} [sourceCandidatePortId]
 * @property {FlowNodeId} [targetNodeId]
 * @property {FlowPortId} [targetPortId]
 * @property {FlowConnectionId} [pendingConnectionId]
 */

/**
 * @typedef {{
 *     type: "node_drag",
 *     nodeId: FlowNodeId,
 *     origin: FlowPosition,
 * } | {
 *     type: "node_resize",
 *     nodeId: FlowNodeId,
 *     origin: FlowSize,
 * } | {
 *     type: "connection_drag",
 *     connectionDraft: FlowConnectionDraft,
 * } | {
 *     type: "pan",
 * }} FlowInteraction
 */

/**
 * @typedef FlowConnection
 * @property {FlowConnectionId} id
 * @property {FlowNodeId} sourceNodeId
 * @property {FlowPortId} sourcePortId
 * @property {FlowNodeId} targetNodeId
 * @property {FlowPortId} targetPortId
 * @property {Record<string, any>} [data]
 */

/** @type {Readonly<FlowViewport>} */
export const DEFAULT_FLOW_VIEWPORT = Object.freeze({ x: 0, y: 0, scale: 1 });
