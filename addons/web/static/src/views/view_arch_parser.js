// @ts-check
/** @odoo-module native */

import { visitXML } from "@web/core/utils/dom/xml";
import { processButton } from "@web/views/view_buttons";
import { Widget } from "@web/views/widgets/widget";

/**
 * @param {Element} node
 * @param {string} attribute
 * @returns {string}
 */
export function requiredAttribute(node, attribute) {
    const value = node.getAttribute(attribute);
    if (value === null) {
        throw new Error(
            `Arch parsing error: <${node.tagName}/> requires a "${attribute}" attribute`,
        );
    }
    return value;
}

/**
 * @param {string | null | undefined} value
 * @returns {boolean | undefined}
 */
export function staticModifier(value) {
    if (value === null || value === undefined || value === "") {
        return false;
    }
    if (value === "1" || value === "True" || value === "true") {
        return true;
    }
    if (value === "0" || value === "False" || value === "false") {
        return false;
    }
    return undefined;
}

export class ViewArchParser {
    /**
     * @abstract
     * @param {Element} _arch
     * @param {Record<string, any>} [_models]
     * @param {string} [_modelName]
     * @returns {any}
     */
    parse(_arch, _models, _modelName) {
        throw new Error(`${this.constructor.name} must implement parse()`);
    }

    /**
     * @template {object} T
     * @param {Element} arch
     * @param {T} archInfo
     * @param {Record<string, (node: Element, archInfo: T) => any>} handlers
     * @returns {T}
     */
    visitArch(arch, archInfo, handlers) {
        visitXML(arch, (node) => {
            const handler = handlers[node.tagName];
            if (handler) {
                return handler.call(this, node, archInfo);
            }
        });
        return archInfo;
    }

    /**
     * @param {Element} node
     * @returns {any}
     */
    processButton(node) {
        return processButton(node);
    }

    /**
     * @param {Element} node
     * @param {Record<string, any>} [_models]
     * @param {string} [_modelName]
     * @returns {any}
     */
    parseWidgetNode(node, _models, _modelName) {
        return Widget.parseWidgetNode(node);
    }

    /**
     * @param {Element} node
     * @param {number} [firstId=0]
     * @returns {any[]}
     */
    parseHeaderButtons(node, firstId = 0) {
        let id = firstId;
        return [...node.children]
            .filter((child) => child.tagName === "button")
            .map((child) => ({
                ...this.processButton(child),
                type: "button",
                id: id++,
            }));
    }

    /**
     * @param {Element} node
     * @returns {any[]}
     */
    parseControls(node) {
        const controls = [];
        for (const child of node.children) {
            switch (child.tagName) {
                case "button":
                    controls.push({ ...this.processButton(child), type: "button" });
                    break;
                case "create":
                    controls.push({
                        type: "create",
                        context: child.getAttribute("context"),
                        string: child.getAttribute("string"),
                        invisible: child.getAttribute("invisible"),
                        class: child.getAttribute("class"),
                    });
                    break;
                case "delete":
                    controls.push({
                        type: "delete",
                        invisible: child.getAttribute("invisible"),
                    });
                    break;
            }
        }
        return controls;
    }
}
