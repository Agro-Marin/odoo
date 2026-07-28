// @ts-check
/** @odoo-module native */

/** @module @web/fields/relational/many2many_tags/many2many_tags_field - Colored tag list field with autocomplete for Many2many relations */

import { Component, useRef } from "@odoo/owl";
import { CheckBox } from "@web/components/checkbox/checkbox";
import { ColorList } from "@web/components/colorlist/colorlist";
import { useTagNavigation } from "@web/components/record_selectors/tag_navigation_hook";
import { TagsList } from "@web/components/tags_list/tags_list";
import { Domain } from "@web/core/domain";
import { _t } from "@web/core/l10n/translation";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { Mutex } from "@web/core/utils/concurrency";
import { useService } from "@web/core/utils/hooks";
import { useRenderCounter } from "@web/core/utils/render_instrumentation";
import { registerField } from "@web/fields/_registry";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { getFieldDomain } from "@web/model/relational_model/utils";
import { usePopover } from "@web/ui/popover/popover_hook";

import { m2oSupportedOptions } from "../many2one/many2one_field.js";
import { Many2XAutocomplete, useOpenMany2XRecord } from "../many2x_autocomplete.js";
import { useActiveActions } from "../relational_active_actions.js";
import { useX2ManyCrud } from "../x2many_crud.js";

/**
 * Colour picker shown when a tag is clicked.
 *
 * It takes the colour to display and two callbacks, and knows nothing about
 * which tag it is editing. It used to receive the tag's datapoint id and hand
 * it back on every callback, which forced the field to re-resolve the record
 * by id at the moment the user picked — long after the popover opened, by
 * which time a reload of the x2many could have replaced the datapoints and
 * the lookup would miss. The field now closes over the record instead, so
 * there is no identity to go stale.
 */
class Many2ManyTagsFieldColorListPopover extends Component {
    static template = "web.Many2ManyTagsFieldColorListPopover";
    static components = {
        CheckBox,
        ColorList,
    };
    static props = {
        colors: Array,
        colorIndex: { type: Number, optional: true },
        switchTagColor: Function,
        onTagVisibilityChange: Function,
        close: Function,
    };
}

export class Many2ManyTagsField extends Component {
    static template = "web.Many2ManyTagsField";
    static components = {
        TagsList,
        Many2XAutocomplete,
    };
    static props = {
        ...standardFieldProps,
        canCreate: { type: Boolean, optional: true },
        canQuickCreate: { type: Boolean, optional: true },
        canCreateEdit: { type: Boolean, optional: true },
        colorField: { type: String, optional: true },
        createDomain: { type: [Array, Boolean], optional: true },
        domain: { type: [Array, Function], optional: true },
        context: { type: Object, optional: true },
        placeholder: { type: String, optional: true },
        nameCreateField: { type: String, optional: true },
        searchThreshold: { type: Number, optional: true },
        string: { type: String, optional: true },
    };
    static defaultProps = {
        canCreate: true,
        canQuickCreate: true,
        canCreateEdit: true,
        nameCreateField: "name",
        context: {},
    };

    static RECORD_COLORS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];

    /** @type {import("services").ServiceFactories["orm"]} */
    orm;
    /** @type {Record<number, any>} */
    previousColorsMap;
    /** @type {any} */
    openMany2xRecord;
    /** @type {any} */
    mutex;
    /** @type {Function} */
    linkRecords;

    setup() {
        useRenderCounter("fields.Many2ManyTagsField");
        this.orm = useService("orm");
        this.previousColorsMap = {};
        useTagNavigation("many2ManyTagsField", {
            isEnabled: () => !this.props.readonly,
            delete: (index) => this.deleteTagByIndex(index),
        });
        this.autoCompleteRef = useRef("autoComplete");
        this.mutex = new Mutex();

        const { linkRecords: maybeLinkRecords, removeRecord } = useX2ManyCrud(
            () => this.props.record.data[this.props.name],
            true,
        );
        const linkRecords = /** @type {Function} */ (maybeLinkRecords);
        this.linkRecords = linkRecords;

        this.activeActions = useActiveActions({
            fieldType: "many2many",
            crudOptions: {
                create: this.props.canCreate && this.props.createDomain,
                createEdit: this.props.canCreateEdit,
                onDelete: removeRecord,
            },
            getEvalParams: (props) => ({
                evalContext: this.evalContext,
                readonly: props.readonly,
                edit: props.record.isInEdition,
            }),
        });

        this.openMany2xRecord = useOpenMany2XRecord(
            /** @type {any} */ ({
                resModel: this.relation,
                activeActions: {
                    create: false,
                    write: true,
                },
                onRecordSaved: (record) => {
                    const records = this.props.record.data[this.props.name].records;
                    return records.find((r) => r.resId === record.resId)?.load();
                },
            }),
        );

        this.update = this.update.bind(this);

        if (this.props.canQuickCreate) {
            this.quickCreate = async (name) => {
                const created = await this.orm.call(
                    this.relation,
                    "name_create",
                    [name],
                    {
                        context: this.props.context,
                    },
                );
                return linkRecords([created[0]]);
            };
        }
    }

    /**
     * Links the given records (not already linked) to the many2many.
     *
     * @param {Array<{ id: number }>|false} recordList
     */
    update(recordList) {
        if (!recordList?.length) {
            return;
        }
        // Membership test against the datapoints, not against `this.tags`:
        // that getter maps EVERY linked record through `getTagProps` and it
        // was re-evaluated once per candidate, so linking 5 records into a
        // 40-tag field ran getTagProps 200 times (measured) — each one an
        // object allocation, and an `imageUrl()` build in the avatar variant.
        // `isSelected` below already did it this way.
        const linkedResIds = new Set(
            this.props.record.data[this.props.name].records.map((r) => r.resId),
        );
        const resIds = recordList
            .filter((element) => !linkedResIds.has(element.id))
            .map((rec) => rec.id);
        if (!resIds.length) {
            return;
        }
        return this.linkRecords(resIds);
    }

    /** @returns {string} Co-model name for the relation */
    get relation() {
        return this.props.record.fields[this.props.name].relation;
    }
    /** @returns {Object} Current record's evaluation context */
    get evalContext() {
        return this.props.record.evalContext;
    }
    /** @returns {string} Human-readable field label */
    get string() {
        return (
            this.props.string || this.props.record.fields[this.props.name].string || ""
        );
    }

    /**
     * @param {Object} record - A relational record from the many2many list
     * @returns {{ id: string, resId: number, text: string, colorIndex: number|undefined, canEdit?: boolean, onDelete: Function|undefined }}
     */
    getTagProps(record) {
        return {
            id: record.id,
            resId: record.resId,
            text: record.data.display_name,
            colorIndex: record.data[this.props.colorField],
            onDelete: !this.props.readonly
                ? () => this.deleteTag(record.id)
                : undefined,
        };
    }

    /** @returns {Array<Object>} Tag props for each linked record */
    get tags() {
        return this.props.record.data[this.props.name].records.map((record) =>
            this.getTagProps(record),
        );
    }

    /** @returns {boolean} */
    get showM2OSelectionField() {
        return !this.props.readonly;
    }

    /** @param {number} index - Zero-based index of the tag to delete */
    async deleteTagByIndex(index) {
        return this.mutex.exec(() => {
            const tag = this.tags[index];
            if (tag) {
                return this._forgetTag(tag.id);
            }
        });
    }

    /** @param {string} id - Datapoint ID of the tag record to remove */
    async deleteTag(id) {
        return this.mutex.exec(() => this._forgetTag(id));
    }

    /**
     * Forgets the tag record with the given id, guarding against a missing
     * record: a double delete can reach here twice for the same id, and after
     * the first removal `find` misses — `forget(undefined)` would throw.
     *
     * @param {string} id - Datapoint ID of the tag record to remove
     */
    _forgetTag(id) {
        const list = this.props.record.data[this.props.name];
        const tagRecord = list.records.find((record) => record.id === id);
        if (!tagRecord) {
            return;
        }
        return list.forget(tagRecord);
    }

    /** @returns {Array} Evaluated domain for the many2many autocomplete search */
    getDomain() {
        return Domain.and([
            getFieldDomain(this.props.record, this.props.name, this.props.domain),
        ]).toList(this.props.context);
    }

    /**
     * @param {{ id: number }} record - Candidate record to check
     * @returns {boolean} Whether the record is already linked
     */
    isSelected(record) {
        const records = this.props.record.data[this.props.name].records;
        return records.some((r) => r.resId === record.id);
    }
}

export const many2ManyTagsField = {
    component: Many2ManyTagsField,
    displayName: _t("Tags"),
    supportedOptions: [
        ...(m2oSupportedOptions ?? []).filter((o) => o.name !== "no_open"),
        {
            label: _t("Can create"),
            name: "create",
            type: "string",
            help: _t("Write a domain to allow the creation of records conditionnally."),
        },
        {
            label: _t("Color field"),
            name: "color_field",
            type: "field",
            isRelationalField: true,
            availableTypes: ["integer"],
            help: _t("Set an integer field to use colors with the tags."),
        },
    ],
    supportedTypes: ["many2many", "one2many"],
    relatedFields: ({ options }) => {
        const relatedFields = [{ name: "display_name", type: "char" }];
        if (options.color_field) {
            relatedFields.push({
                name: options.color_field,
                type: "integer",
                readonly: false,
            });
        }
        return relatedFields;
    },
    extractProps({ attrs, options, string, placeholder }, dynamicInfo) {
        const hasCreatePermission = attrs.can_create
            ? evaluateBooleanExpr(attrs.can_create)
            : true;
        const noCreate = Boolean(options.no_create);
        const canCreate = noCreate ? false : hasCreatePermission;
        const noQuickCreate = Boolean(options.no_quick_create);
        const noCreateEdit = Boolean(options.no_create_edit);
        return {
            colorField: options.color_field,
            nameCreateField: options.create_name_field,
            canCreate,
            canQuickCreate: canCreate && !noQuickCreate,
            canCreateEdit: canCreate && !noCreateEdit,
            createDomain: options.create,
            context: dynamicInfo.context,
            domain: dynamicInfo.domain,
            placeholder,
            searchThreshold: options.search_threshold,
            string,
        };
    },
};

registerField(
    {
        name: "many2many_tags",
        aliases: [
            { name: "one2many", view: "calendar" },
            { name: "many2many", view: "calendar" },
        ],
    },
    many2ManyTagsField,
);

/** Specialization that allows editing the tag color via the colorpicker (form view). */
export class Many2ManyTagsFieldColorEditable extends Many2ManyTagsField {
    static props = {
        ...super.props,
        canEditColor: { type: Boolean, optional: true },
        canEditTags: { type: Boolean, optional: true },
    };
    static defaultProps = {
        ...super.defaultProps,
        canEditColor: true,
        canEditTags: false,
    };

    /** @type {any} */
    popover;

    setup() {
        super.setup();
        // The colour picker belongs to this variant only. The base class used
        // to run `usePopover(this.constructor.components.Popover)`, which
        // resolved to `undefined` for every widget except this one — a base
        // class carrying a subclass's dependency.
        this.popover = usePopover(Many2ManyTagsFieldColorListPopover);
    }

    /** @override */
    getTagProps(record) {
        const props = /** @type {any} */ (super.getTagProps(record));
        props.canEdit = this.props.canEditTags;
        props.onClick = (ev) => this.onTagClick(ev, record);
        return props;
    }

    /**
     * @param {MouseEvent} ev
     * @param {Object} record - The tag's relational record
     */
    onTagClick(ev, record) {
        if (this.props.canEditTags) {
            return this.openMany2xRecord({
                resId: record.resId,
                context: this.props.context,
                title: _t("Edit: %s", record.data.display_name),
            });
        }
        if (!this.props.canEditColor) {
            return;
        }
        if (this.popover.isOpen) {
            this.popover.close();
        } else {
            this.popover.open(/** @type {HTMLElement} */ (ev.currentTarget), {
                colors: /** @type {any} */ (this.constructor).RECORD_COLORS,
                colorIndex: record.data[this.props.colorField],
                // Bind the record itself rather than its datapoint id: the
                // callbacks fire whenever the user picks, and the record the
                // colour belongs to must not be re-derived from a list that
                // may have been reloaded in between.
                switchTagColor: (colorIndex) => this.switchTagColor(colorIndex, record),
                onTagVisibilityChange: (isHidden) =>
                    this.onTagVisibilityChange(isHidden, record),
            });
        }
    }

    /**
     * @param {boolean} isHidden - Whether to hide (color=0) or restore the tag
     * @param {Object} tagRecord - The tag's relational record
     */
    async onTagVisibilityChange(isHidden, tagRecord) {
        if (tagRecord.data[this.props.colorField] !== 0) {
            this.previousColorsMap[tagRecord.resId] =
                tagRecord.data[this.props.colorField];
        }
        const changes = {
            [this.props.colorField]: isHidden
                ? 0
                : this.previousColorsMap[tagRecord.resId] || 1,
        };
        await tagRecord.update(changes);
        await tagRecord.save();
        this.popover.close();
    }

    /**
     * @param {number} colorIndex - New color index to assign
     * @param {Object} tagRecord - The tag's relational record
     */
    async switchTagColor(colorIndex, tagRecord) {
        await tagRecord.update({ [this.props.colorField]: colorIndex });
        await tagRecord.save();
        this.popover.close();
    }
}

export const many2ManyTagsFieldColorEditable = {
    ...many2ManyTagsField,
    component: Many2ManyTagsFieldColorEditable,
    supportedOptions: [
        ...many2ManyTagsField.supportedOptions,
        {
            label: _t("Prevent color edition"),
            name: "no_edit_color",
            type: "boolean",
        },
        {
            label: _t("Edit Tags"),
            name: "edit_tags",
            type: "boolean",
            help: _t(
                "If checked, clicking on the tag will open the form that allows to directly edit it. Note that if a color field is also set, the tag edition will prevail. So, the color picker will not be displayed on click on the tag.",
            ),
        },
    ],
    extractProps: (fieldInfo, dynamicInfo) => {
        const { attrs, options } = fieldInfo;
        const hasEditPermission = attrs.can_write
            ? evaluateBooleanExpr(attrs.can_write)
            : true;
        const canEditTags = options.edit_tags ? hasEditPermission : false;
        return {
            ...many2ManyTagsField.extractProps(fieldInfo, dynamicInfo),
            canEditTags,
            canEditColor:
                !canEditTags && !options.no_edit_color && !!options.color_field,
        };
    },
};

registerField(
    { name: "many2many_tags", view: "form" },
    many2ManyTagsFieldColorEditable,
);
