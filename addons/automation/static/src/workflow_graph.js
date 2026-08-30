/** @odoo-module native */

import { _t } from "@web/core/translation";

export const NODE_WIDTH = 180;
export const NODE_HEIGHT = 44;

const NAME_LIMIT = 24;

export function canConnect(edges, sourceId, targetId) {
    if (!sourceId || !targetId || sourceId === targetId) {
        return false;
    }
    return !edges.some((edge) => edge.source === sourceId && edge.target === targetId);
}

export function nodeClasses(node) {
    const classes = ["o_workflow_canvas_node"];
    if (node.node_type && node.node_type !== "action") {
        classes.push(`o_workflow_canvas_type_${node.node_type}`);
    }
    if (node.runtime_state) {
        classes.push(`o_workflow_canvas_run_${node.runtime_state}`);
    }
    return classes.join(" ");
}

export function linkClasses(edge) {
    return `o_workflow_canvas_link o_workflow_canvas_${edge.condition}`;
}

export function conditionLabel(condition) {
    return {
        on_success: _t("on success"),
        on_error: _t("on error"),
        always: _t("always"),
        expression: _t("if"),
    }[condition];
}

export function shortName(name) {
    if (!name) {
        return "";
    }
    return name.length > NAME_LIMIT ? `${name.slice(0, NAME_LIMIT - 1)}…` : name;
}
