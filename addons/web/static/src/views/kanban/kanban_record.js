// @ts-check
/** @odoo-module native */

/** @module @web/views/kanban/kanban_record - Individual kanban card component with compiled template, color strips, cover images, and action handling */

import { Component, onWillStart, onWillUpdateProps, useRef } from "@odoo/owl";
import { ColorList } from "@web/components/colorlist/colorlist";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { browser } from "@web/core/browser/browser";
import { hasTouch } from "@web/core/browser/feature_detection";
import { luxon } from "@web/core/l10n/luxon";
import { _t } from "@web/core/l10n/translation";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { imageUrl } from "@web/core/utils/urls";
import { Field } from "@web/fields/field";
import { fileTypeMagicWordMap } from "@web/fields/media/image/image_field";
import { ViewButton } from "@web/views/view_button/view_button";
import { useViewCompiler } from "@web/views/view_compiler";
import { getFormattedValue } from "@web/views/view_utils";
import { Widget } from "@web/views/widgets/widget";

import { KANBAN_CARD_ATTRIBUTE, KANBAN_MENU_ATTRIBUTE } from "./kanban_arch_parser.js";
import { KanbanCompiler } from "./kanban_compiler.js";
import { KanbanCoverImageDialog } from "./kanban_cover_image_dialog.js";
import { KanbanDropdownMenuWrapper } from "./kanban_dropdown_menu_wrapper.js";

const { COLORS } = ColorList;

const formatters = registry.category("formatters");

// These classes determine whether a click on a record should open it.
export const CANCEL_GLOBAL_CLICK = [
    "a",
    ".dropdown",
    ".oe_kanban_action",
    "[data-bs-toggle]",
].join(",");

function getColorIndex(value) {
    if (typeof value === "number") {
        return Math.round(value) % COLORS.length;
    } else if (typeof value === "string") {
        const codePointSum = [...value].reduce(
            (acc, char) => acc + char.codePointAt(0),
            0,
        );
        return codePointSum % COLORS.length;
    } else {
        return 0;
    }
}

/**
 * Returns a "raw" version of the field value on a given record.
 *
 * @param {any} record
 * @param {string} fieldName
 * @returns {any}
 */
export function getRawValue(record, fieldName) {
    const field = record.fields[fieldName];
    const value = record.data[fieldName];
    switch (field.type) {
        case "one2many":
        case "many2many": {
            return value.count ? value.currentIds : [];
        }
        case "many2one": {
            return value?.id || false;
        }
        case "date":
        case "datetime": {
            return typeof value?.toISO === "function" ? value.toISO() : value;
        }
        default: {
            return value;
        }
    }
}

/**
 * Returns a formatted version of the field value on a given record.
 *
 * @param {any} record
 * @param {string} fieldName
 * @returns {string}
 */
function getValue(record, fieldName) {
    const field = record.fields[fieldName];
    const value = record.data[fieldName];
    const formatter = formatters.get(field.type, String);
    return formatter(value, { field, data: record.data });
}

/**
 * Returns a lazily formatted version of a record for the card template's
 * rendering context: `id` and each active field expose `value`/`raw_value`
 * accessors computed on read rather than eagerly, so only accessed fields
 * are formatted and reactively subscribed.
 *
 * @param {any} record
 * @returns {any}
 */
export function getFormattedRecord(record) {
    const entries = Object.create(null);
    const getEntry = (fieldName) => {
        if (!entries[fieldName]) {
            if (fieldName === "id") {
                entries[fieldName] = {
                    get value() {
                        return record.resId;
                    },
                    get raw_value() {
                        return record.resId;
                    },
                };
            } else {
                entries[fieldName] = {
                    get value() {
                        return getValue(record, fieldName);
                    },
                    get raw_value() {
                        return getRawValue(record, fieldName);
                    },
                };
            }
        }
        return entries[fieldName];
    };
    const isField = (p) =>
        typeof p === "string" && (p === "id" || record.fieldNames.includes(p));
    return new Proxy(Object.create(null), {
        get(target, p) {
            return isField(p) ? getEntry(p) : Reflect.get(target, p);
        },
        has(target, p) {
            return isField(p) || Reflect.has(target, p);
        },
        ownKeys(target) {
            return [
                ...new Set(["id", ...record.fieldNames, ...Reflect.ownKeys(target)]),
            ];
        },
        getOwnPropertyDescriptor(target, p) {
            if (isField(p)) {
                return { enumerable: true, configurable: true, value: getEntry(p) };
            }
            return Reflect.getOwnPropertyDescriptor(target, p);
        },
    });
}

/**
 * Returns the image URL of a given field on the record.
 *
 * @param {any} record
 * @param {string} [model] model name
 * @param {string} [field] field name
 * @param {number | [number, ...any[]]} [idOrIds] id or array
 *      starting with the id of the desired record.
 * @param {string} [placeholder] fallback when the image does not
 *  exist
 * @returns {string}
 */
export function getImageSrcFromRecordInfo(record, model, field, idOrIds, placeholder) {
    const id = (Array.isArray(idOrIds) ? idOrIds[0] : idOrIds) || null;
    const isCurrentRecord =
        record.resModel === model && (record.resId === id || (!record.resId && !id));
    const fieldVal = record.data[field];
    if (isCurrentRecord && fieldVal && !isBinSize(fieldVal)) {
        // Use magic-word technique for detecting image type
        const type = fileTypeMagicWordMap[fieldVal[0]];
        return `data:image/${type};base64,${fieldVal}`;
    } else if (placeholder && (!model || !field || !id || !fieldVal)) {
        return placeholder;
    } else {
        const unique = isCurrentRecord && record.data.write_date;
        return imageUrl(model, id, field, { unique });
    }
}

function isBinSize(value) {
    return /^\d+(\.\d*)? [^0-9]+$/.test(value);
}

export class KanbanRecord extends Component {
    static components = {
        Dropdown,
        DropdownItem,
        KanbanDropdownMenuWrapper,
        Field,
        KanbanCoverImageDialog,
        ViewButton,
        Widget,
    };
    static defaultProps = {
        colors: COLORS,
        deleteRecord: () => {},
        getSelection: () => [],
        archiveRecord: () => {},
        openRecord: () => {},
        selectionAvailable: false,
        toggleSelection: () => {},
    };
    static props = [
        "archInfo",
        "canResequence?",
        "colors?",
        "Compiler?",
        "forceGlobalClick?",
        "getSelection?",
        "group?",
        "groupByField?",
        "deleteRecord?",
        "archiveRecord?",
        "openRecord?",
        "readonly?",
        "record",
        "selectionAvailable?",
        "progressBarState?",
        "toggleSelection?",
    ];
    static KANBAN_CARD_ATTRIBUTE = KANBAN_CARD_ATTRIBUTE;
    static KANBAN_MENU_ATTRIBUTE = KANBAN_MENU_ATTRIBUTE;
    static menuTemplate = "web.KanbanRecordMenu";
    static template = "web.KanbanRecord";

    setup() {
        this.LONG_TOUCH_THRESHOLD = this.props.canResequence ? 600 : 400;
        this.evaluateBooleanExpr = evaluateBooleanExpr;
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");

        const { Compiler, archInfo } = this.props;
        const ViewCompiler = Compiler || KanbanCompiler;
        const { templateDocs: templates } = archInfo;

        this.templates = useViewCompiler(ViewCompiler, templates);

        this.showMenu =
            /** @type {any} */ (this.constructor).KANBAN_MENU_ATTRIBUTE in templates;

        this.createWidget(this.props);
        this.formattedRecord = getFormattedRecord(this.props.record);
        onWillUpdateProps((nextProps) => {
            this.createWidget(nextProps);
            if (nextProps.record !== this.props.record) {
                this.formattedRecord = getFormattedRecord(nextProps.record);
            }
        });
        // Mount across a microtask boundary (previously an implicit effect
        // of the removed record-observer hook's async onWillStart): without
        // it, a card on a fiber about to be superseded would render on the
        // discarded fiber, wasting work and breaking a render-count assert
        // pinned by the kanban test suite.
        onWillStart(() => Promise.resolve());
        this.rootRef = useRef("root");
        this.hasTouch = hasTouch();

        this.longTouchTimer = null;
        this.touchStartMs = 0;
    }

    get record() {
        return this.formattedRecord;
    }

    getFormattedValue(fieldId) {
        const { archInfo, record } = this.props;
        const { name } = archInfo.fieldNodes[fieldId];
        return getFormattedValue(record, name, archInfo.fieldNodes[fieldId]);
    }

    /**
     * Assigns "widget" properties on the kanban record.
     *
     * @param {Object} props
     */
    createWidget(props) {
        const { archInfo, groupByField } = props;
        const { activeActions } = archInfo;
        // Widget
        const deletable =
            activeActions.delete &&
            (!groupByField || groupByField.type !== "many2many") &&
            !props.readonly;
        const editable = activeActions.edit && !props.readonly;
        this.widget = {
            deletable,
            editable,
        };
    }

    getRecordClasses() {
        const { archInfo, canResequence, forceGlobalClick, record, progressBarState } =
            this.props;
        const classes = ["o_kanban_record d-flex"];
        if (canResequence) {
            classes.push("o_draggable");
        }
        if (forceGlobalClick || archInfo.openAction || archInfo.canOpenRecords) {
            classes.push("cursor-pointer");
        }
        if (progressBarState) {
            const { fieldName, colors } = progressBarState.progressAttributes;
            const value = record.data[fieldName];
            const color = colors[value];
            if (color) {
                classes.push(`oe_kanban_card_${color}`);
            }
        }
        if (archInfo.cardColorField) {
            const value = record.data[archInfo.cardColorField];
            classes.push(`o_kanban_color_${getColorIndex(value)}`);
        }
        if (!this.props.groupByField) {
            classes.push("flex-grow-1 flex-md-shrink-1 flex-shrink-0");
        }
        if (this.props.selectionAvailable) {
            classes.push("o_record_selection_available");
        }
        if (this.props.record.selected) {
            classes.push("o_record_selected");
        }
        classes.push(archInfo.cardClassName);
        return classes.join(" ");
    }

    /**
     * @param {MouseEvent} ev
     */
    onGlobalClick(ev, newWindow) {
        if (/** @type {HTMLElement} */ (ev.target).closest(CANCEL_GLOBAL_CLICK)) {
            return;
        }
        if (this.props.getSelection().length > 0 || ev.altKey) {
            ev.stopPropagation();
            ev.preventDefault();
            this.rootRef.el.focus();
            this.props.toggleSelection(this.props.record, ev.shiftKey);
            return;
        }
        const { archInfo, forceGlobalClick, openRecord, record } = this.props;
        if (!forceGlobalClick && archInfo.openAction) {
            this.action.doActionButton(
                {
                    name: archInfo.openAction.action,
                    type: archInfo.openAction.type,
                    resModel: record.resModel,
                    resId: record.resId,
                    resIds: record.resIds,
                    context: record.context,
                    onClose: async () => {
                        await record.model.root.load();
                    },
                },
                {
                    newWindow,
                },
            );
        } else if (forceGlobalClick || this.props.archInfo.canOpenRecords) {
            openRecord(record, { newWindow });
        }
    }

    resetLongTouchTimer() {
        if (this.longTouchTimer) {
            browser.clearTimeout(this.longTouchTimer);
            this.longTouchTimer = null;
        }
    }

    onTouchStart() {
        this.touchStartMs = Date.now();
        if (this.longTouchTimer === null) {
            this.longTouchTimer = browser.setTimeout(() => {
                this.props.record.toggleSelection(true);
                this.resetLongTouchTimer();
            }, this.LONG_TOUCH_THRESHOLD);
        }
    }
    onTouchEnd() {
        const elapsedTime = Date.now() - this.touchStartMs;
        if (elapsedTime < this.LONG_TOUCH_THRESHOLD) {
            this.resetLongTouchTimer();
        }
    }
    onTouchMoveOrCancel() {
        this.resetLongTouchTimer();
    }

    /**
     * @param {Object} params
     */
    triggerAction(params) {
        const { archInfo, openRecord, deleteRecord, record, archiveRecord } =
            this.props;
        const { type } = params;
        switch (type) {
            case "open": {
                return openRecord(record);
            }
            case "archive": {
                return archiveRecord(record, true);
            }
            case "unarchive": {
                return archiveRecord(record, false);
            }
            case "delete": {
                return deleteRecord(record);
            }
            case "set_cover": {
                const { fieldName } = params;
                const widgets = Object.values(archInfo.fieldNodes)
                    .filter((x) => x.name === fieldName)
                    .map((x) => x.widget);
                const field = record.fields[fieldName];
                if (
                    field.type === "many2one" &&
                    field.relation === "ir.attachment" &&
                    widgets.includes("attachment_image")
                ) {
                    this.dialog.add(KanbanCoverImageDialog, {
                        fieldName,
                        record,
                    });
                } else {
                    const warning = _t(
                        `Could not set the cover image: incorrect field ("%s") is provided in the view.`,
                        fieldName,
                    );
                    this.notification.add(warning, { type: "danger" });
                }
                break;
            }
            default: {
                return this.notification.add(
                    _t("Kanban: no action for type: %(type)s", { type }),
                    {
                        type: "danger",
                    },
                );
            }
        }
    }

    /**
     * Returns the card template's rendering context. The keys follow
     * outdated conventions but must not be changed, for compatibility.
     *
     * @returns {Object}
     */
    get renderingContext() {
        const renderingContext = {
            context: this.props.record.context,
            JSON,
            luxon,
            record: this.formattedRecord,
            selection_mode: this.props.forceGlobalClick,
            widget: this.widget,
            __comp__: Object.assign(Object.create(this), { this: this }),
        };
        return renderingContext;
    }
}
