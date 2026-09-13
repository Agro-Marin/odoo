/** @odoo-module native */
import { isSmallInteger } from "@html_builder/utils/utils";
import { generateHTMLId } from "@html_builder/utils/utils_css";
import { makeLogger } from "@web/core/debug/debug_logger";
import { _t } from "@web/core/translation";
import { escape } from "@web/core/utils/format/strings";
import { renderToElement } from "@web/core/utils/render";

export const VISIBILITY_DATASET = [
    "visibilityDependency",
    "visibilityCondition",
    "visibilityComparator",
    "visibilityBetween",
];

const log = makeLogger("website.builder.plugin.form_utils");

/**
 * @param {string} formId
 * @param {HTMLElement} parentEl
 * @returns {Object|undefined}
 */
export function getParsedDataFor(formId, parentEl) {
    const dataForEl = parentEl.querySelector(`[data-for='${formId}']`);
    if (!dataForEl) {
        return;
    }
    return JSON.parse(
        dataForEl.dataset.values
            .replace(/([,:[]\s*)True/g, "$1true")
            .replace(/([,:[]\s*)(False|None)/g, '$1""')
            .replace(/'(\s*[,:\]}])/g, '"$1')
            .replace(/([{[:,]\s*)'/g, '$1"'),
    );
}

/**
 * @param {string} type
 * @param {string} label
 * @param {string} [name]
 * @returns {Object}
 */
export function getCustomField(type, label, name = "") {
    return {
        name: name || label,
        string: label,
        custom: true,
        type: type,
        records: [
            {
                id: _t("Option 1"),
                display_name: _t("Option 1"),
            },
            {
                id: _t("Option 2"),
                display_name: _t("Option 2"),
            },
            {
                id: _t("Option 3"),
                display_name: _t("Option 3"),
            },
        ],
    };
}

export const getMark = (el) => el.dataset.mark;
export const isOptionalMark = (el) => el.classList.contains("o_mark_optional");
export const isRequiredMark = (el) => el.classList.contains("o_mark_required");
/**
 * @param {HTMLElement} el
 * @returns {Object}
 */
export function getDefaultFormat(el) {
    return {
        labelWidth: el.querySelector(".s_website_form_label").style.width,
        labelPosition: "left",
        multiPosition: "horizontal",
        requiredMark: isRequiredMark(el),
        optionalMark: isOptionalMark(el),
        mark: getMark(el),
    };
}

/**
 * @param {string} name
 * @returns {string}
 */
export function getQuotesEncodedName(name) {
    return name.replaceAll(/"/g, (character) => `&quot;`);
}

/**
 * @param {Object} field
 * @returns {HTMLElement}
 */
export function renderField(field, resetId = false) {
    const endRender = log.perf("renderField", () => ({
        name: field.name,
        type: field.type,
    }));
    if (!field.id) {
        field.id = generateHTMLId();
    }
    const params = {
        field: { ...field },
        defaultName: escape(field.string || _t("Field")),
    };
    if (["url", "email", "tel"].includes(field.type)) {
        params.field.inputType = field.type;
    }
    if (["boolean", "selection"].includes(field.type)) {
        params.field.isCheck = true;
    }
    if (field.type === "one2many" && field.relation !== "ir.attachment") {
        params.field.isCheck = true;
    }
    if (field.custom && !field.string) {
        params.field.string = field.name;
    }
    if (field.description) {
        params.default_description = _t("Describe your field here.");
    } else if (["email_cc", "email_to"].includes(field.name)) {
        params.default_description = _t("Separate email addresses with a comma.");
    }
    const template = document.createElement("template");
    const renderType = field.type === "tags" ? "many2many" : field.type;
    template.content.append(
        renderToElement("website.form_field_" + renderType, params),
    );
    if (field.description && field.description !== true) {
        const descriptionEl = template.content.querySelector(
            ".s_website_form_field_description",
        );
        descriptionEl.replaceWith(field.description);
    }
    template.content
        .querySelectorAll("input.datetimepicker-input")
        .forEach((el) => (el.value = field.propertyValue));
    template.content.querySelectorAll("[name]").forEach((el) => {
        el.name = getQuotesEncodedName(el.name);
    });
    template.content.querySelectorAll("[data-name]").forEach((el) => {
        el.dataset.name = getQuotesEncodedName(el.dataset.name);
    });
    template.content.querySelectorAll(".s_website_form_field").forEach((el) => {
        if (field.formatInfo.offset) {
            el.classList.add(field.formatInfo.offset);
        }
    });
    endRender();
    return template.content.firstElementChild;
}

/**
 * @param {HTMLElement} fieldEl
 * @returns {boolean}
 */
export function isFieldRequired(fieldEl) {
    const classList = fieldEl.classList;
    return (
        classList.contains("s_website_form_required") ||
        classList.contains("s_website_form_model_required")
    );
}

/**
 * @param {HTMLElement} fieldEl
 * @returns {HTMLElement}
 */
export function getMultipleInputs(fieldEl) {
    return fieldEl.querySelector(".s_website_form_multiple");
}

export function getLabelPosition(fieldEl) {
    const label = fieldEl.querySelector(".s_website_form_label");
    if (fieldEl.querySelector(".row:not(.s_website_form_multiple)")) {
        return label.classList.contains("text-end") ? "right" : "left";
    } else {
        return label.classList.contains("d-none") ? "none" : "top";
    }
}

/**
 * @param {HTMLElement} fieldEl
 * @returns {Object}
 */
export function getFieldFormat(fieldEl) {
    let requiredMark, optionalMark;
    const mark = fieldEl.querySelector(".s_website_form_mark");
    if (mark) {
        requiredMark = isFieldRequired(fieldEl);
        optionalMark = !requiredMark;
    }
    const multipleInputEl = getMultipleInputs(fieldEl);
    const format = {
        labelPosition: getLabelPosition(fieldEl),
        labelWidth: fieldEl.querySelector(".s_website_form_label").style.width,
        multiPosition:
            (multipleInputEl && multipleInputEl.dataset.display) || "horizontal",
        col: [...fieldEl.classList].filter((el) => el.match(/^col-/g)).join(" "),
        offset: [...fieldEl.classList].filter((el) => el.match(/^offset-/g)).join(" "),
        requiredMark: requiredMark,
        optionalMark: optionalMark,
        mark: mark && mark.textContent,
    };
    return format;
}

/**
 * @param {HTMLElement} fieldEl
 * @returns {boolean}
 */
export function isFieldCustom(fieldEl) {
    return !!fieldEl.classList.contains("s_website_form_custom");
}

/**
 * @param {HTMLElement} fieldEl
 * @returns {string}
 */
export function getFieldName(fieldEl = this.$target[0]) {
    const multipleName = fieldEl.querySelector(".s_website_form_multiple");
    return multipleName
        ? multipleName.dataset.name
        : fieldEl.querySelector(".s_website_form_input").name;
}
/**
 * @param {HTMLElement} fieldEl
 * @returns {string}
 */
export function getFieldType(fieldEl) {
    return fieldEl.dataset.type;
}

/**
 * @param {HTMLElement} fieldEl
 * @param {Object} field
 */
export function setActiveProperties(fieldEl, field) {
    const classList = fieldEl.classList;
    const textarea = fieldEl.querySelector("textarea");
    const input = fieldEl.querySelector(
        'input[type="text"], input[type="email"], input[type="number"], input[type="tel"], input[type="url"], textarea',
    );
    const fileInputEl = fieldEl.querySelector("input[type=file]");
    const description = fieldEl.querySelector(".s_website_form_field_description");
    field.placeholder = input?.placeholder || "";
    if (input) {
        field.value = input.getAttribute("value") || input.value;
    } else if (field.type === "boolean") {
        field.value = !!fieldEl.querySelector('input[type="checkbox"][checked]');
    } else if (fileInputEl) {
        field.maxFilesNumber = fileInputEl.dataset.maxFilesNumber;
        field.maxFileSize = fileInputEl.dataset.maxFileSize;
    }
    field.propertyValue = input && input.value;
    field.description = description;
    field.rows = textarea && textarea.rows;
    field.required = classList.contains("s_website_form_required");
    field.modelRequired = classList.contains("s_website_form_model_required");
    field.hidden = classList.contains("s_website_form_field_hidden");
    field.formatInfo = getFieldFormat(fieldEl);
}

/**
 * @param {HTMLElement} oldFieldEl
 * @param {HTMLElement} fieldEl
 */
export function replaceFieldElement(oldFieldEl, fieldEl) {
    const inputEl = oldFieldEl.querySelector("input");
    const dataFillWith = inputEl ? inputEl.dataset.fillWith : undefined;
    const hasConditionalVisibility = oldFieldEl.classList.contains(
        "s_website_form_field_hidden_if",
    );
    const previousInputEl = oldFieldEl.querySelector(".s_website_form_input");
    const previousName = previousInputEl.name;
    const previousType = previousInputEl.type;
    [...oldFieldEl.childNodes].forEach((node) => node.remove());
    [...fieldEl.childNodes].forEach((node) => oldFieldEl.appendChild(node));
    [...fieldEl.attributes].forEach((el) => oldFieldEl.removeAttribute(el.nodeName));
    [...fieldEl.attributes].forEach((el) =>
        oldFieldEl.setAttribute(el.nodeName, el.nodeValue),
    );
    if (hasConditionalVisibility) {
        oldFieldEl.classList.add("s_website_form_field_hidden_if", "d-none");
    }
    const dependentFieldEls = oldFieldEl
        .closest("form")
        .querySelectorAll(
            `.s_website_form_field[data-visibility-dependency="${CSS.escape(previousName)}"]`,
        );
    const newFormInputEl = oldFieldEl.querySelector(".s_website_form_input");
    const newName = newFormInputEl.name;
    const newType = newFormInputEl.type;
    log.logic("replaceFieldElement", () => ({
        previousName,
        newName,
        previousType,
        newType,
        dependents: dependentFieldEls.length,
        clearDependents: previousName !== newName || previousType !== newType,
    }));
    if ((previousName !== newName || previousType !== newType) && dependentFieldEls) {
        for (const fieldEl of dependentFieldEls) {
            deleteConditionalVisibility(fieldEl);
        }
    }
    const newInputEl = oldFieldEl.querySelector("input");
    if (newInputEl) {
        newInputEl.dataset.fillWith = dataFillWith;
    }
}

/**
 * @param {HTMLElement} fieldEl
 * @param {boolean} noRecords
 * @returns {Object}
 */
export function getActiveField(fieldEl, { noRecords, fields } = {}) {
    let field;
    const labelText =
        fieldEl.querySelector(".s_website_form_label_content")?.innerText || "";
    if (isFieldCustom(fieldEl)) {
        const inputName = fieldEl
            .querySelector(".s_website_form_input")
            .getAttribute("name");
        field = getCustomField(fieldEl.dataset.type, labelText, inputName);
    } else {
        field = Object.assign({}, fields[getFieldName(fieldEl)]);
        field.string = labelText;
        field.type = getFieldType(fieldEl);
    }
    if (!noRecords) {
        field.records = getListItems(fieldEl);
    }
    setActiveProperties(fieldEl, field);
    return field;
}

/**
 * @param {HTMLElement} fieldEl
 */
export function deleteConditionalVisibility(fieldEl) {
    log.pipeline("deleteConditionalVisibility", () => ({
        dependency: fieldEl.dataset.visibilityDependency,
    }));
    for (const name of VISIBILITY_DATASET) {
        delete fieldEl.dataset[name];
    }
    fieldEl.classList.remove("s_website_form_field_hidden_if", "d-none");
}

/**
 * @param {HTMLElement} fieldEl
 * @returns {HTMLElement}
 */
export function getSelect(fieldEl) {
    return fieldEl.querySelector("select");
}

/**
 * @param {HTMLElement} fieldEl
 */
export function getNewRecordId(fieldEl) {
    const selectEl = getSelect(fieldEl);
    const multipleInputsEl = getMultipleInputs(fieldEl);
    let options = [];
    if (selectEl) {
        options = [...selectEl.querySelectorAll("option")];
    } else if (multipleInputsEl) {
        options = [
            ...multipleInputsEl.querySelectorAll(".checkbox input, .radio input"),
        ];
    }
    const targetEl = fieldEl.querySelector(".s_website_form_input");
    let id;
    if (["checkbox", "radio"].includes(targetEl.getAttribute("type"))) {
        id = targetEl.id.slice(0, -1);
    } else {
        id = targetEl.id;
    }
    return id + options.length;
}

/**
 * @param {HTMLElement} fieldEl
 * @returns {HTMLElement}
 */
export function getDependencyEl(fieldEl) {
    const dependencyName = fieldEl.dataset.visibilityDependency;
    return fieldEl
        .closest("form")
        ?.querySelector(`.s_website_form_input[name="${CSS.escape(dependencyName)}"]`);
}

/**
 * @param {HTMLElement} fieldEl
 * @returns {HTMLElement}
 */
export function getCurrentFieldInputEl(fieldEl) {
    return fieldEl.querySelector(".s_website_form_input");
}

/**
 * @param {HTMLElement} dependentFieldEl
 * @param {HTMLElement} targetFieldEl
 * @returns {boolean}
 */
export function findCircular(dependentFieldEl, targetFieldEl) {
    const formEl = targetFieldEl.closest("form");
    const visitedFields = new Set();
    const recursiveFindCircular = (dependentFieldEl, targetFieldEl) => {
        const dependentFieldName = getFieldName(dependentFieldEl);
        let dependentFieldEls = Array.from(
            formEl.querySelectorAll(
                `.s_website_form_input[name="${CSS.escape(dependentFieldName)}"]`,
            ),
        ).map((el) => el.closest(".s_website_form_field"));
        dependentFieldEls = new Set(dependentFieldEls);
        const fieldName = getFieldName(targetFieldEl);
        for (const dependentFieldEl of dependentFieldEls) {
            if (!visitedFields.has(dependentFieldEl)) {
                visitedFields.add(dependentFieldEl);
                if (dependentFieldEl.dataset.visibilityDependency === fieldName) {
                    return true;
                }
                const dependencyInputEl = getDependencyEl(dependentFieldEl);
                if (
                    dependencyInputEl &&
                    recursiveFindCircular(
                        dependencyInputEl.closest(".s_website_form_field"),
                        targetFieldEl,
                    )
                ) {
                    return true;
                }
            }
        }
        return false;
    };
    return recursiveFindCircular(dependentFieldEl, targetFieldEl);
}

/**
 * @param {HTMLElement} formEl
 * @param {String} name
 * @param {String} type
 * @param {String} relation
 * @returns {Object|false}
 */
const allFormsInfo = new Map();
export function getDomain(formEl, name, type, relation) {
    if (!allFormsInfo.get(formEl) || !name || !type || !relation) {
        return false;
    }
    const field = allFormsInfo
        .get(formEl)
        .fields.find(
            (el) => el.name === name && el.type === type && el.relation === relation,
        );
    return field && field.domain;
}

export function getModelName(formEl) {
    return formEl.dataset.model_name || "mail.mail";
}

export function getListItems(fieldEl) {
    const selectEl = getSelect(fieldEl);
    const multipleInputsEl = getMultipleInputs(fieldEl);
    let options = [];
    if (selectEl) {
        options = [...selectEl.querySelectorAll("option")];
    } else if (multipleInputsEl) {
        options = [
            ...multipleInputsEl.querySelectorAll(".checkbox input, .radio input"),
        ];
    }
    return options.map((opt) => {
        const name = selectEl ? opt : opt.nextElementSibling;
        return {
            id: isSmallInteger(opt.value) ? parseInt(opt.value) : opt.value,
            display_name: name.textContent.trim(),
            selected: selectEl ? opt.selected : opt.checked,
        };
    });
}

/**
 * @param {HTMLElement} fieldEl
 * @param {string} value
 */
export function setVisibilityDependency(fieldEl, value) {
    log.pipeline("setVisibilityDependency", () => ({
        from: fieldEl.dataset.visibilityDependency,
        to: value,
    }));
    delete fieldEl.dataset.visibilityCondition;
    delete fieldEl.dataset.visibilityComparator;
    fieldEl.dataset.visibilityDependency = value;
}

/**
 * @param {HTMLElement} fieldEl
 * @param {Object<string, Object>} fields
 */
export function rerenderField(fieldEl, fields) {
    const field = getActiveField(fieldEl, { fields });
    log.pipeline("rerenderField", () => ({ name: field.name, type: field.type }));
    delete field.id;
    const newFieldEl = renderField(field);
    replaceFieldElement(fieldEl, newFieldEl);
}
