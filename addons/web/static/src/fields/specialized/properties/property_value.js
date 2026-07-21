// @ts-check
/** @odoo-module native */

/** @module @web/fields/specialized/properties/property_value - Polymorphic value editor component supporting all property field types */

import { Component, useRef } from "@odoo/owl";
import { CheckBox } from "@web/components/checkbox/checkbox";
import { DateTimeInput } from "@web/components/datetime/datetime_input";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { TagsList } from "@web/components/tags_list/tags_list";
import { Domain } from "@web/core/domain";
import { ModelEvent } from "@web/core/events";
import {
    deserializeDate,
    deserializeDateTime,
    formatDate,
    formatDateTime,
    serializeDate,
    serializeDateTime,
} from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";
import { deepCopy } from "@web/core/utils/collections/objects";
import { formatFloat } from "@web/core/utils/format/numbers";
import { nbsp } from "@web/core/utils/format/strings";
import { useBus, useService } from "@web/core/utils/hooks";
import { imageUrl } from "@web/core/utils/urls";
import { formatInteger, formatMany2one, formatMonetary } from "@web/fields/formatters";
import { parseFloat, parseInteger, parseMonetary } from "@web/fields/parsers";
import { extractData } from "@web/fields/relational/many2one/many2one";
import {
    Many2XAutocomplete,
    useOpenMany2XRecord,
} from "@web/fields/relational/many2x_autocomplete";
import { getCurrency } from "@web/services/currency";

import { PropertyTags } from "./property_tags.js";
import { PropertyText } from "./property_text.js";

/**
 * Renders the appropriate editor for a property value based on its type
 * (text, integer, boolean, selection, date(time), many2one, many2many,
 * monetary, tags, ...).
 */
export class PropertyValue extends Component {
    static template = "web.PropertyValue";
    static components = {
        Dropdown,
        DropdownItem,
        CheckBox,
        DateTimeInput,
        Many2XAutocomplete,
        TagsList,
        PropertyTags,
        PropertyText,
    };

    static props = {
        id: { type: String, optional: true },
        type: { type: String, optional: true },
        comodel: { type: String, optional: true },
        currencyField: { type: String, optional: true },
        domain: { type: String, optional: true },
        string: { type: String, optional: true },
        value: { optional: true },
        context: { type: Object },
        readonly: { type: Boolean, optional: true },
        canChangeDefinition: { type: Boolean, optional: true },
        selection: { type: Array, optional: true },
        tags: { type: Array, optional: true },
        onChange: { type: Function, optional: true },
        onTagsChange: { type: Function, optional: true },
        record: { type: Object, optional: true },
    };

    setup() {
        this.nbsp = nbsp;

        this.orm = useService("orm");
        this.action = useService("action");

        // Flush a typed-but-unblurred raw-input value on save. The property
        // inputs commit only on the native ``change`` (blur) event, but neither
        // Ctrl+S (``record.save()`` → NEED_LOCAL_CHANGES) nor tab-close (the
        // beacon urgent save → WILL_SAVE_URGENTLY) blurs the input, so the value
        // was silently dropped from the write. Only the FOCUSED input can hold an
        // uncommitted value (anything else already committed on blur), so commit
        // exactly that one and let the save await the mutex-queued update. The
        // ``text`` type uses the PropertyText child, which flushes itself.
        // ``record`` is optional on this component, so guard on it.
        if (this.props.record) {
            /** @type {any} */
            this.inputRef = useRef("input");
            const flush = (ev) => {
                const el = this.inputRef.el;
                if (el && el === document.activeElement) {
                    ev.detail?.proms?.push(this.onValueChange(el.value));
                }
            };
            useBus(this.props.record.model.bus, ModelEvent.NEED_LOCAL_CHANGES, flush);
            useBus(this.props.record.model.bus, ModelEvent.WILL_SAVE_URGENTLY, flush);
        }

        this.openMany2X = useOpenMany2XRecord(
            /** @type {any} */ ({
                resModel: this.props.comodel,
                activeActions: {
                    create: false,
                    createEdit: false,
                    write: true,
                },
                isToMany: false,
                onRecordSaved: async (record) => {
                    if (!record || record.resId == null) {
                        // A dialog onchange may have cleared the record: nothing
                        // to refetch and orm.read([undefined]) is malformed.
                        return;
                    }
                    // maybe the record display name has changed
                    // CROSS-GROUP(name_service): bespoke orm.read bypasses the
                    // shared name_service cache (see many2one.js).
                    const records = await this.orm.read(
                        record.resModel,
                        [record.resId],
                        ["display_name"],
                        {
                            context: this.props.context,
                        },
                    );
                    const recordData = extractData(records[0]);
                    await this.onValueChange([recordData]);
                },
                fieldString: this.props.string,
            }),
        );
    }

    /* --------------------------------------------------------
     * Public methods / Getters
     * -------------------------------------------------------- */

    get currency() {
        if (!isNaN(this.currencyId)) {
            return getCurrency(this.currencyId) || null;
        }
        return null;
    }

    get currencyId() {
        const currency = this.props.record.data[this.props.currencyField];
        return currency && currency.id;
    }

    /**
     * Value of the current property, shaped for the sub-components.
     *
     * @returns {object}
     */
    get propertyValue() {
        const value = this.props.value;

        if (this.props.type === "float") {
            // force to show at least 1 digit, even for integers
            return value;
        } else if (this.props.type === "datetime") {
            const datetimeValue =
                typeof value === "string" ? deserializeDateTime(value) : value;
            return datetimeValue && !datetimeValue.invalid ? datetimeValue : false;
        } else if (this.props.type === "date") {
            const dateValue =
                typeof value === "string" ? deserializeDate(value) : value;
            return dateValue && !dateValue.invalid ? dateValue : false;
        } else if (this.props.type === "boolean") {
            return !!value;
        } else if (this.props.type === "selection") {
            const options = this.props.selection || [];
            const option = options.find((option) => option[0] === value);
            return option && option.length === 2 && option[0] ? option[0] : "";
        } else if (this.props.type === "many2one") {
            return !value || !value.id || !value.display_name ? false : value;
        } else if (this.props.type === "many2many") {
            if (!value || !value.length) {
                return [];
            }

            // Convert to TagsList component format
            return value.map((many2manyValue) => {
                const hasAccess = many2manyValue[1] !== null;
                return {
                    id: many2manyValue[0],
                    comodel: this.props.comodel,
                    text: hasAccess ? many2manyValue[1] : _t("No Access"),
                    onClick:
                        hasAccess &&
                        this.clickableRelational &&
                        (async () =>
                            await this._openRecord(
                                this.props.comodel,
                                many2manyValue[0],
                            )),
                    onDelete:
                        !this.props.readonly &&
                        hasAccess &&
                        (() => this.onMany2manyDelete(many2manyValue[0])),
                    colorIndex: 0,
                    img:
                        this.showAvatar && hasAccess
                            ? imageUrl(
                                  this.props.comodel,
                                  many2manyValue[0],
                                  "avatar_128",
                              )
                            : null,
                };
            });
        } else if (this.props.type === "tags") {
            return value || [];
        }

        return value;
    }

    /**
     * Return the model domain (related to many2one and many2many properties).
     *
     * @returns {array}
     */
    get propertyDomain() {
        if (!this.props.domain || !this.props.domain.length) {
            return [];
        }
        let domain = new Domain(this.props.domain);
        if (this.props.type === "many2many" && this.props.value) {
            domain = Domain.and([
                domain,
                [["id", "not in", this.props.value.map((rec) => rec[0])]],
            ]);
        }
        return domain.toList();
    }

    /**
     * Formatted value displayed in readonly mode.
     *
     * @returns {string}
     */
    get displayValue() {
        const value = this.propertyValue;

        if (this.props.type === "many2one" && value && value.id) {
            return formatMany2one(value);
        } else if (this.props.type === "integer") {
            return formatInteger(value || 0);
        } else if (this.props.type === "float") {
            return formatFloat(value || 0);
        } else if (this.props.type === "monetary") {
            return formatMonetary(value || 0, {
                digits: this.currency?.digits,
                currencyId: this.currencyId,
                noSymbol: !this.props.readonly,
            });
        } else if (!value) {
            return /** @type {any} */ (false);
        } else if (this.props.type === "datetime" && value) {
            return formatDateTime(value);
        } else if (this.props.type === "date" && value) {
            return formatDate(value);
        } else if (this.props.type === "selection") {
            return (
                this.props.selection.find((option) => option[0] === value)?.[1] ?? value
            );
        }
        return value.toString();
    }

    /**
     * Return true if the relational properties are clickable.
     *
     * @returns {boolean}
     */
    get clickableRelational() {
        return !this.env.config || this.env.config.viewType !== "kanban";
    }

    /**
     * Return True if we need to display a avatar for the current property.
     *
     * @returns {boolean}
     */
    get showAvatar() {
        return (
            ["many2one", "many2many"].includes(this.props.type) &&
            ["res.users", "res.partner"].includes(this.props.comodel)
        );
    }

    /* --------------------------------------------------------
     * Event handlers
     * -------------------------------------------------------- */

    /**
     * Parse the value received by the sub-components and trigger an onChange event.
     *
     * @param {object} newValue
     */
    async onValueChange(newValue) {
        if (this.props.type === "datetime") {
            newValue = newValue && serializeDateTime(newValue);
        } else if (this.props.type === "date") {
            newValue = newValue && serializeDate(newValue);
        } else if (this.props.type === "integer") {
            try {
                newValue = parseInteger(newValue) || 0;
            } catch {
                newValue = 0;
            }
        } else if (this.props.type === "float") {
            try {
                newValue = parseFloat(newValue) || 0;
            } catch {
                newValue = 0;
            }
        } else if (["many2one", "many2many"].includes(this.props.type)) {
            newValue = newValue[0];
            if (newValue && newValue.id && newValue.display_name === undefined) {
                // "Search more" only returns the record ID, not the name —
                // resolve the display name via RPC so it can be shown.
                newValue = await this._nameGet(newValue.id);
            }

            if (this.props.type === "many2many" && newValue) {
                const currentValue = this.props.value || [];
                const recordId = newValue.id;
                const exists = currentValue.find((rec) => rec[0] === recordId);
                if (exists) {
                    return;
                }
                newValue = [...currentValue, [newValue.id, newValue.display_name]];
            }
        } else if (this.props.type === "monetary") {
            try {
                newValue = parseMonetary(newValue) || 0;
            } catch {
                newValue = 0;
            }
        }

        // trigger the onchange event to notify the parent component. Return the
        // resulting promise (``onPropertyValueChange`` → ``_updateRecordProperties``,
        // queued on model.mutex) so the save-flush can await it before serializing.
        return this.props.onChange(newValue);
    }

    /**
     * Open the form view of the current record.
     *
     * @param {event} event
     */
    async onMany2oneClick(event) {
        if (this.props.readonly) {
            event.stopPropagation();
            await this._openRecord(this.props.comodel, this.propertyValue.id);
        }
    }

    /**
     * Open the current many2one record form view in a modal.
     */
    onExternalLinkClick() {
        return this.openMany2X({
            resId: this.propertyValue.id,
            forceModel: this.props.comodel,
            context: this.props.context,
        });
    }

    /**
     * Removed a record from the many2many list.
     *
     * @param {integer} many2manyId
     */
    onMany2manyDelete(many2manyId) {
        const currentValue = deepCopy(this.props.value || []);
        const newValue = currentValue.filter((value) => value[0] !== many2manyId);
        this.props.onChange(newValue);
    }

    /**
     * Ask to create a record from a relational property.
     *
     * @param {string} name
     */
    async onQuickCreate(name) {
        const result = await this.orm.call(this.props.comodel, "name_create", [name], {
            context: this.props.context,
        });
        this.onValueChange([{ id: result[0], display_name: result[1] }]);
    }

    /* --------------------------------------------------------
     * Private methods
     * -------------------------------------------------------- */

    /**
     * Open the form view of the given record id / model.
     *
     * @param {string} recordModel
     * @param {integer} recordId
     */
    async _openRecord(recordModel, recordId) {
        const action = await this.orm.call(
            recordModel,
            "get_formview_action",
            [[recordId]],
            {
                context: this.props.context,
            },
        );

        this.action.doAction(action);
    }

    /**
     * Get the display name of the given record.
     * Model is taken from the current selected model.
     *
     * @param {number} recordId
     * @returns {Promise<any>}
     */
    async _nameGet(recordId) {
        if (recordId == null) {
            return { id: recordId, display_name: false };
        }
        const result = await this.orm.read(
            this.props.comodel,
            [recordId],
            ["display_name"],
            {
                context: this.props.context,
            },
        );
        return result[0] || { id: recordId, display_name: false };
    }
}
