/** @odoo-module native */
import { BuilderAction } from "@html_builder/core/builder_action";
import { ClassAction } from "@html_builder/core/core_builder_action_plugin";
import { applyFunDependOnSelectorAndExclude } from "@html_builder/plugins/utils";
import { after } from "@html_builder/utils/option_sequence";
import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { uniqueId } from "@web/core/utils/functions";
import { CONTAINER_WIDTH } from "@website/builder/option_sequence";

import { BaseWebsiteBackgroundOption } from "./background_option.js";
import { connectorOptionParams, ProcessStepsOption } from "./process_steps_option.js";

const log = makeLogger("website.builder.plugin.process_steps_option");

export class WebsiteBackgroundProcessStepOption extends BaseWebsiteBackgroundOption {
    static selector = ".s_process_step .s_process_step_number";
    static defaultProps = {
        withColors: true,
        withImages: false,
        withColorCombinations: false,
    };
}

class ProcessStepsOptionPlugin extends Plugin {
    static id = "processStepsOption";
    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_options: [
            withSequence(after(CONTAINER_WIDTH), ProcessStepsOption),
            WebsiteBackgroundProcessStepOption,
        ],
        builder_actions: {
            ChangeConnectorAction,
            ChangeArrowColorAction,
        },
        content_updated_handlers: (rootEl) =>
            applyFunDependOnSelectorAndExclude(reloadConnectors, rootEl, {
                selector: ProcessStepsOption.selector,
            }),
        dropzone_selector: {
            selector: ".s_process_step",
            dropLockWithin: ".s_process_steps",
        },
    };
}

export class ChangeConnectorAction extends ClassAction {
    static id = "changeConnector";
    apply({ editingElement, params: { mainParam: className } }) {
        super.apply(...arguments);
        reloadConnectors(editingElement);
        let markerEnd = "";
        if (
            [
                "s_process_steps_connector_arrow",
                "s_process_steps_connector_curved_arrow",
            ].includes(className)
        ) {
            const arrowHeadEl = editingElement.querySelector(
                ".s_process_steps_arrow_head",
            );
            if (!arrowHeadEl.id) {
                log.logic("ChangeConnectorAction assign arrow head id");
                arrowHeadEl.id = uniqueId("s_process_steps_arrow_head");
            }
            markerEnd = `url(#${arrowHeadEl.id})`;
        }
        log.pipeline("ChangeConnectorAction apply", () => ({ className, markerEnd }));
        editingElement
            .querySelectorAll(".s_process_step_connector path")
            .forEach((path) => path.setAttribute("marker-end", markerEnd));
    }
}

export class ChangeArrowColorAction extends BuilderAction {
    static id = "changeArrowColor";
    apply({ editingElement, value: colorValue }) {
        const arrowHeadEl = editingElement
            .closest(".s_process_steps")
            .querySelector(".s_process_steps_arrow_head");
        log.pipeline("ChangeArrowColorAction apply", () => ({ colorValue }));
        arrowHeadEl.querySelector("path").style.fill = colorValue;
    }
}

registry
    .category("website-plugins")
    .add(ProcessStepsOptionPlugin.id, ProcessStepsOptionPlugin);

function reloadConnectors(editingElement) {
    const connectorOptionClasses = connectorOptionParams.map(
        (connectorOptionParam) => connectorOptionParam.key,
    );
    const type =
        connectorOptionClasses.find(
            (connectorOptionClass) =>
                connectorOptionClass &&
                editingElement.classList.contains(connectorOptionClass),
        ) || "";
    const stepsEls = editingElement.querySelectorAll(
        ".s_process_step:not(.o_snippet_desktop_invisible)",
    );
    const nbBootstrapCols = 12;
    let colsInRow = 0;
    const endReload = log.perf("reloadConnectors", () => ({
        type,
        steps: stepsEls.length,
    }));

    for (let i = 0; i < stepsEls.length - 1; i++) {
        const connectorEl = stepsEls[i].querySelector(".s_process_step_connector");
        const stepMainElementRect = getStepMainElementRect(stepsEls[i]);
        const nextStepMainElementRect = getStepMainElementRect(stepsEls[i + 1]);
        const stepSize = getClassSuffixedInteger(stepsEls[i], "col-lg-");
        const nextStepSize = getClassSuffixedInteger(stepsEls[i + 1], "col-lg-");
        const stepOffset = getClassSuffixedInteger(stepsEls[i], "offset-lg-");
        const nextStepOffset = getClassSuffixedInteger(stepsEls[i + 1], "offset-lg-");
        const stepPaddingTop = getClassSuffixedInteger(stepsEls[i], "pt");
        const nextStepPaddingTop = getClassSuffixedInteger(stepsEls[i + 1], "pt");
        const stepHeightDifference = stepPaddingTop - nextStepPaddingTop;
        const hCurrentStepIconHeight = stepMainElementRect.height / 2;
        const hNextStepIconHeight = nextStepMainElementRect.height / 2;

        connectorEl.style.left = `calc(50% + ${stepMainElementRect.width / 2}px + 16px)`;
        connectorEl.style.height = `${
            stepMainElementRect.height + Math.abs(stepHeightDifference)
        }px`;
        connectorEl.style.width = `calc(${
            (100 * (stepSize / 2 + nextStepOffset + nextStepSize / 2)) / stepSize
        }% - ${stepMainElementRect.width / 2}px - ${nextStepMainElementRect.width / 2}px - 32px)`;

        const marginType = stepHeightDifference < 0 ? "marginBottom" : "marginTop";
        connectorEl.style[marginType] = `${0 - Math.abs(stepHeightDifference)}px`;

        const isTheLastColOfRow =
            nbBootstrapCols <
            colsInRow + stepSize + stepOffset + nextStepSize + nextStepOffset;
        connectorEl.classList.toggle("d-none", isTheLastColOfRow);
        colsInRow = isTheLastColOfRow ? 0 : colsInRow + stepSize + stepOffset;
        connectorEl.style.display = "block";
        const { height, width } = connectorEl.getBoundingClientRect();
        connectorEl.style.removeProperty("display");
        if (type === "s_process_steps_connector_curved_arrow" && i % 2 === 0) {
            connectorEl.style.transform = stepHeightDifference
                ? "unset"
                : "scale(1, -1)";
        } else {
            connectorEl.style.transform = "unset";
        }
        connectorEl.setAttribute("viewBox", `0 0 ${width} ${height}`);
        connectorEl
            .querySelector("path")
            .setAttribute(
                "d",
                getPath(
                    type,
                    width,
                    height,
                    stepHeightDifference,
                    hCurrentStepIconHeight,
                    hNextStepIconHeight,
                ),
            );
    }
    endReload();
}
/**
 * @param {HTMLElement} el
 * @param {String} classNamePrefix
 * @returns {Integer}
 */
function getClassSuffixedInteger(el, classNamePrefix) {
    const className = [...el.classList].find((cl) => cl.startsWith(classNamePrefix));
    return className ? parseInt(className.replace(classNamePrefix, "")) : 0;
}
/**
 * @returns {object}
 */
function getStepMainElementRect(stepEl) {
    const iconEl = stepEl.querySelector(".s_process_step_number");
    if (iconEl) {
        return iconEl.getBoundingClientRect();
    }
    const contentEls = stepEl.querySelectorAll(".s_process_step_content > *");
    if (contentEls.length) {
        const contentRects = [...contentEls].map((contentEl) => {
            const range = document.createRange();
            range.selectNodeContents(contentEl);
            return range.getBoundingClientRect();
        });
        return contentRects.reduce((previous, current) =>
            current.width > previous.width ? current : previous,
        );
    }
    return {};
}
/**
 * @param {string} type
 * @param {integer} width
 * @param {integer} height
 * @returns {string}
 */
function getPath(
    type,
    width,
    height,
    stepHeightDifference,
    hCurrentStepIconHeight,
    hNextStepIconHeight,
) {
    const hHeight = height / 2;
    switch (type) {
        case "s_process_steps_connector_line": {
            const verticalPaddingFactor = Math.abs(stepHeightDifference) / 8;
            if (stepHeightDifference >= 0) {
                return `M 0 ${
                    stepHeightDifference +
                    hCurrentStepIconHeight -
                    verticalPaddingFactor
                } L ${width} ${hNextStepIconHeight + verticalPaddingFactor}`;
            }
            return `M 0 ${hCurrentStepIconHeight + verticalPaddingFactor} L ${width} ${
                hNextStepIconHeight - stepHeightDifference - verticalPaddingFactor
            }`;
        }
        case "s_process_steps_connector_arrow": {
            const verticalPaddingFactor = (Math.abs(stepHeightDifference) / 8) * 1.5;
            if (stepHeightDifference >= 0) {
                return `M ${0.05 * width} ${
                    stepHeightDifference +
                    hCurrentStepIconHeight -
                    verticalPaddingFactor
                } L ${0.95 * width - 6} ${hNextStepIconHeight + verticalPaddingFactor}`;
            }
            return `M ${0.05 * width} ${hCurrentStepIconHeight + verticalPaddingFactor} L ${
                0.95 * width - 6
            } ${Math.abs(stepHeightDifference) + hNextStepIconHeight - verticalPaddingFactor}`;
        }
        case "s_process_steps_connector_curved_arrow": {
            if (stepHeightDifference === 0) {
                return `M ${0.05 * width} ${hHeight * 1.2} Q ${width / 2} ${hHeight * 1.8} ${
                    0.95 * width - 6
                } ${hHeight * 1.2}`;
            } else if (stepHeightDifference > 0) {
                return `M ${0.05 * width} ${stepHeightDifference + hCurrentStepIconHeight} Q ${
                    width * 0.75
                } ${height * 0.75} ${0.5 * width - 6} ${hHeight} T ${
                    0.95 * width - 6
                } ${hNextStepIconHeight}`;
            }
            return `M ${0.05 * width} ${hCurrentStepIconHeight} Q ${width * 0.75} ${
                height * 0.005
            } ${0.5 * width - 6} ${hHeight} T ${0.95 * width - 6} ${
                Math.abs(stepHeightDifference) + hNextStepIconHeight
            }`;
        }
    }
    return "";
}
