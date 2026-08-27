// @ts-check
/** @odoo-module native */

import { Component, useRef } from "@odoo/owl";
import { CheckBox } from "@web/components/checkbox/checkbox";
import { ColorList } from "@web/components/colorlist/colorlist";
import { useTagNavigation } from "@web/components/record_selectors/tag_navigation_hook";
import { TagsList } from "@web/components/tags_list/tags_list";
import { _t } from "@web/core/translation";
import { Mutex } from "@web/core/utils/concurrency";
import { useService } from "@web/core/utils/hooks";
import { useRenderCounter } from "@web/core/utils/render_instrumentation";
import { registerField } from "@web/fields/_registry";
import { FieldComponent } from "@web/fields/field_component";
import {
    colorFieldOption,
    createPermissionAttribute,
    writePermissionAttribute,
} from "@web/fields/field_options";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { getFieldDomain } from "@web/model/relational_model";
import { usePopover } from "@web/ui/popover/popover_hook";

import {
    extractCreatePermissions,
    extractWritePermission,
    m2oSupportedOptions,
} from "../many2one/many2one_field.js";
import { Many2XAutocomplete, useOpenMany2XRecord } from "../many2x_autocomplete.js";
import { useActiveActions } from "../relational_active_actions.js";
import { useX2ManyCrud } from "../x2many_crud.js";

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

/**
 * @param {Record<string, any>} a
 * @param {Record<string, any>} b
 * @returns {boolean}
 */
function sameTagProps(a, b) {
    const keys = Object.keys(a);
    if (keys.length !== Object.keys(b).length) {
        return false;
    }
    return keys.every((key) =>
        typeof a[key] === "function" ? typeof b[key] === "function" : a[key] === b[key],
    );
}

export class Many2ManyTagsField extends FieldComponent {
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
        searchMemoization: { type: String, optional: true },
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
    /** @type {import("../relational_active_actions").RelationalActiveActions} */
    activeActions;
    /** @type {((name: string) => Promise<any>) | undefined} */
    quickCreate;
    /** @type {{ records: any[], tags: any[] } | null} */
    _tagsMemo = null;

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

        const { linkRecords, removeRecord } = useX2ManyCrud(
            () => this.field.value,
            true,
        );
        this.linkRecords = linkRecords;

        this.activeActions = useActiveActions({
            fieldType: "many2many",
            crudOptions: (props) => ({
                create: props.canCreate && props.createDomain,
                createEdit: props.canCreateEdit,
                onDelete: removeRecord,
            }),
            getEvalParams: (props) => ({
                evalContext: props.record.evalContext,
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
                    const records = this.field.value.records;
                    return records.find((r) => r.resId === record.resId)?.load();
                },
            }),
        );

        this.update = this.update.bind(this);
        this.getDomain = this.getDomain.bind(this);

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
     * @param {Array<{ id: number }>|false} recordList
     */
    update(recordList) {
        if (!recordList || !recordList.length) {
            return;
        }
        const linkedResIds = new Set(this.field.value.records.map((r) => r.resId));
        const resIds = recordList
            .filter((element) => !linkedResIds.has(element.id))
            .map((rec) => rec.id);
        if (!resIds.length) {
            return;
        }
        return this.linkRecords(resIds);
    }

    /** @returns {string} */
    get relation() {
        return this.field.definition.relation;
    }
    /** @returns {string} */
    get string() {
        return this.props.string || this.field.definition.string || "";
    }

    /**
     * @param {Object} record
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

    /**
     * @returns {Array<Object>}
     */
    get tags() {
        const records = this.field.value.records;
        const tags = records.map((record) => this.getTagProps(record));
        const memo = this._tagsMemo;
        if (
            memo &&
            memo.records.length === records.length &&
            memo.records.every((record, i) => record === records[i]) &&
            memo.tags.every((tag, i) => sameTagProps(tag, tags[i]))
        ) {
            return memo.tags;
        }
        this._tagsMemo = { records: [...records], tags };
        return tags;
    }

    /** @returns {boolean} */
    get showM2OSelectionField() {
        return !this.props.readonly;
    }

    /**
     * @returns {Object}
     */
    get many2XAutocompleteProps() {
        return {
            activeActions: this.activeActions,
            autoSelect: true,
            context: this.props.context,
            fieldString: this.string,
            getDomain: this.getDomain,
            id: this.props.id,
            isToMany: true,
            nameCreateField: this.props.nameCreateField,
            placeholder: this.tags.length ? "" : this.props.placeholder,
            quickCreate: this.activeActions.create ? (this.quickCreate ?? null) : null,
            resModel: this.relation,
            searchMemoization: this.props.searchMemoization,
            searchThreshold: this.props.searchThreshold,
            update: this.update,
        };
    }

    /** @param {number} index */
    async deleteTagByIndex(index) {
        return this.mutex.exec(() => {
            const tag = this.tags[index];
            if (tag) {
                return this._forgetTag(tag.id);
            }
        });
    }

    /** @param {string} id */
    async deleteTag(id) {
        return this.mutex.exec(() => this._forgetTag(id));
    }

    /**
     * @param {string} id
     */
    _forgetTag(id) {
        const list = this.field.value;
        const tagRecord = list.records.find((record) => record.id === id);
        if (!tagRecord) {
            return;
        }
        return list.forget(tagRecord);
    }

    /** @returns {Array} */
    getDomain() {
        return getFieldDomain(this.props.record, this.props.name, this.props.domain);
    }

    /**
     * @param {{ id: number }} record
     * @returns {boolean}
     */
    isSelected(record) {
        const records = this.field.value.records;
        return records.some((r) => r.resId === record.id);
    }
}

export const many2ManyTagsField = {
    component: Many2ManyTagsField,
    displayName: _t("Tags"),
    supportedOptions: [
        ...(m2oSupportedOptions ?? []).filter(
            (o) => !["no_open", "can_scan_barcode"].includes(o.name),
        ),
        {
            label: _t("Can create"),
            name: "create",
            type: "string",
            help: _t("Write a domain to allow the creation of records conditionnally."),
        },
        colorFieldOption(_t("Set an integer field to use colors with the tags."), {
            isRelationalField: true,
        }),
    ],
    supportedAttributes: [createPermissionAttribute()],
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
    extractProps(
        /** @type {any} */ { attrs, options, string, placeholder },
        /** @type {any} */ dynamicInfo,
    ) {
        return {
            ...extractCreatePermissions({ attrs, options }),
            colorField: options.color_field,
            nameCreateField: options.create_name_field,
            createDomain: options.create,
            context: dynamicInfo.context,
            domain: dynamicInfo.domain,
            placeholder,
            searchMemoization: options.search_memoization,
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
     * @param {Object} record
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
                switchTagColor: (colorIndex) => this.switchTagColor(colorIndex, record),
                onTagVisibilityChange: (isHidden) =>
                    this.onTagVisibilityChange(isHidden, record),
            });
        }
    }

    /**
     * @param {boolean} isHidden
     * @param {Object} tagRecord
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
     * @param {number} colorIndex
     * @param {Object} tagRecord
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
    supportedAttributes: [
        ...many2ManyTagsField.supportedAttributes,
        writePermissionAttribute(),
    ],
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
    extractProps: (/** @type {any} */ fieldInfo, /** @type {any} */ dynamicInfo) => {
        const { options } = fieldInfo;
        const canEditTags = options.edit_tags
            ? extractWritePermission(fieldInfo)
            : false;
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
