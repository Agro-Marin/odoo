// @ts-check
/** @odoo-module native */

/** @module @web/fields/specialized/properties/properties_field - Dynamic property field editor with drag-and-drop reordering and inline definition */

import {
    Component,
    onWillStart,
    onWillUpdateProps,
    useEffect,
    useRef,
    useState,
} from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { ModelEvent } from "@web/core/events";
import { _t } from "@web/core/l10n/translation";
import { reposition } from "@web/core/position/utils";
import { exprToBoolean, uuid } from "@web/core/utils/format/strings";
import { useBus, useService } from "@web/core/utils/hooks";
import { registerField } from "@web/fields/_registry";
import { useRecordObserver } from "@web/fields/hooks/record_observer";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { user } from "@web/services/user";
import { ConfirmationDialog } from "@web/ui/dialog/confirmation_dialog";
import { usePopover } from "@web/ui/popover/popover_hook";

import { usePropertiesSortable } from "./properties_sortable_hook.js";
import { PropertyDefinition } from "./property_definition.js";
import { PropertyValue } from "./property_value.js";

export class PropertiesField extends Component {
    static template = "web.PropertiesField";
    static components = {
        Dropdown,
        DropdownItem,
        PropertyDefinition,
        PropertyValue,
    };
    static props = {
        ...standardFieldProps,
        context: { type: Object, optional: true },
        columns: {
            type: Number,
            optional: true,
            validate: (columns) => [1, 2].includes(columns),
        },
        editMode: { type: Boolean, optional: true },
    };

    setup() {
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.dialogService = useService("dialog");
        this.popover = usePopover(PropertyDefinition, {
            closeOnClickAway: this.checkPopoverClose,
            popoverClass: "o_property_field_popover",
            position: "right",
            onClose: () => this.onCloseCurrentPopover?.(),
            fixedPosition: true,
            arrow: false,
            setActiveElement: false, // make tag navigation work when adding a tag property
        });
        this.propertiesRef = useRef("properties");
        // Prefix used to build stable DOM ids for the properties (one uuid
        // per component instance instead of one per property per render).
        this.domIdPrefix = `property_${uuid()}`;

        let currentResId;
        useRecordObserver((record) => {
            if (currentResId !== record.resId) {
                currentResId = record.resId;
                this._saveInitialPropertiesValues();
            }
        });

        const field = this.props.record.fields[this.props.name];
        this.definitionRecordField = field.definition_record;

        this.state = useState({
            canChangeDefinition: false,
            isInEditMode: false,
            movedPropertyName: null,
        });

        // Properties can be added from the cog menu of the form controller
        if (this.env.config?.viewType === "form") {
            useBus(this.env.model.bus, ModelEvent.PROPERTY_FIELD_EDIT, async () => {
                if (this.props.readonly || this.state.isInEditMode) {
                    return;
                }
                const isInEditMode = await this._recomputeEditMode(this.props, {
                    force: true,
                });
                if (!this.state.canChangeDefinition) {
                    this.notification.add(this._getPropertyEditWarningText(), {
                        type: "warning",
                    });
                }
                if (isInEditMode && !this.propertiesList.length) {
                    this.onPropertyCreate();
                }
            });
        }

        onWillStart(async () => {
            if (this.props.readonly || !this.props.editMode) {
                return;
            }
            await this._recomputeEditMode();
        });

        useEffect(
            () => {
                // when the field has a new definition record:
                if (
                    this.props.readonly ||
                    (!this.state.isInEditMode && !this.props.editMode)
                ) {
                    return;
                }
                this._recomputeEditMode(this.props, { recheck: true });
            },
            () => [this.props.record.data[this.definitionRecordField]],
        );

        onWillUpdateProps(async (nextProps) => {
            if (nextProps.readonly && !this.props.readonly) {
                this.state.isInEditMode = false;
            }
            if (
                !nextProps.readonly &&
                (this.props.readonly || (nextProps.editMode && !this.props.editMode))
            ) {
                await this._recomputeEditMode(nextProps);
            }
        });

        useEffect(
            () => {
                if (this.openPropertyDefinition) {
                    const propertyName = this.openPropertyDefinition;
                    const labels = this.propertiesRef.el.querySelectorAll(
                        `.o_property_field[property-name="${propertyName}"] .o_field_property_open_popover`,
                    );
                    this.openPropertyDefinition = null;
                    const lastLabel = labels[labels.length - 1];
                    this._openPropertyDefinition(lastLabel, propertyName, true);
                }
            },
            () => [this.openPropertyDefinition],
        );

        useEffect(() => this._movePopoverIfNeeded());

        usePropertiesSortable({
            propertiesRef: this.propertiesRef,
            getEnabled: () => !this.props.readonly && this.state.canChangeDefinition,
            getRenderedColumnsCount: () => this.renderedColumnsCount,
            getGroupedPropertiesList: () => this.groupedPropertiesList,
            onPropertyMoveTo: (from, to, moveBefore) =>
                this.onPropertyMoveTo(from, to, moveBefore),
            onGroupMoveTo: (from, to) => this.onGroupMoveTo(from, to),
            onToggleSeparators: (names, force) => this._toggleSeparators(names, force),
        });
    }

    /* --------------------------------------------------------
     * Public methods / Getters
     * -------------------------------------------------------- */

    /**
     * Return the number of columns to render (properties can be split
     * across columns to follow the form view's layout).
     *
     * @returns {object}
     */
    get renderedColumnsCount() {
        return this.env.isSmall ? 1 : this.props.columns;
    }

    /**
     * Return a deep copy of the properties values, so mutating them in
     * event handlers doesn't touch the record's stored objects (e.g. so
     * discarding the form view still restores the original props).
     *
     * @returns {array}
     */
    get propertiesList() {
        return (this.props.record.data[this.props.name] || [])
            .filter((definition) => !definition.definition_deleted)
            .map((definition) => ({ ...definition }));
    }

    // for overrides
    get additionalPropertyDefinitionProps() {
        return {};
    }

    /**
     * Split the properties into groups (by separator), then split the
     * groups into columns. Order matters since separators define the
     * group boundaries.
     *
     * @returns {any[]}
     */
    get groupedPropertiesList() {
        const propertiesList = this.propertiesList;
        // default invisible group
        const groupedProperties =
            propertiesList[0]?.type !== "separator"
                ? [
                      {
                          title: null,
                          name: null,
                          elements: [],
                          invisibleLabel: true,
                      },
                  ]
                : [];

        propertiesList.forEach((property) => {
            if (property.type === "separator") {
                groupedProperties.push(
                    /** @type {any} */ ({
                        title: property.string,
                        name: property.name,
                        elements: [],
                        isFolded: property.value ?? property.fold_by_default,
                    }),
                );
            } else {
                groupedProperties.at(-1).elements.push(property);
            }
        });

        if (groupedProperties.length === 1) {
            // only one group, split this group in the columns to take the entire width
            const invisibleLabel = propertiesList[0]?.type !== "separator";
            groupedProperties[0].elements = [];
            groupedProperties[0].invisibleLabel = invisibleLabel;
            for (let col = 1; col < this.renderedColumnsCount; ++col) {
                groupedProperties.push({
                    title: null,
                    name: null,
                    columnSeparator: true,
                    elements: [],
                    invisibleLabel: true,
                });
            }
            const properties = propertiesList.filter(
                (property) => property.type !== "separator",
            );
            properties.forEach((property, index) => {
                const columnIndex = Math.floor(
                    (index * this.renderedColumnsCount) / properties.length,
                );
                groupedProperties[columnIndex].elements.push(property);
            });
        }

        return groupedProperties;
    }

    /**
     * Return the id of the definition record.
     *
     * @returns {integer}
     */
    get definitionRecordId() {
        return this.props.record.data[this.definitionRecordField].id;
    }

    /**
     * Return the model of the definition record.
     *
     * @returns {string}
     */
    get definitionRecordModel() {
        return this.props.record.fields[this.definitionRecordField].relation;
    }

    /**
     * Whether the properties-definition popover should close for the given
     * click target. Widgets like the datetime picker or many2one modal
     * render outside the popover's DOM subtree, so clicks inside them must
     * not close it.
     *
     * @param {HTMLElement} target
     * @returns {boolean}
     */
    checkPopoverClose(target) {
        if (target.closest(".o_datetime_picker")) {
            // selected a datetime, do not close the definition popover
            return false;
        }

        if (target.closest(".modal")) {
            // close a many2one modal
            return false;
        }

        if (target.closest(".o_tag_popover")) {
            // tag color popover
            return false;
        }

        if (target.closest(".o_model_field_selector_popover")) {
            // domain selector
            return false;
        }

        return true;
    }

    /**
     * Return a unique but render-stable ID to be used in the DOM for the
     * given property.
     *
     * @param {string} propertyName
     * @returns {string}
     */
    getPropertyDomID(propertyName) {
        return `${this.domIdPrefix}_${propertyName}`;
    }

    /**
     * Generate a new property name.
     *
     * @returns {string}
     */
    generatePropertyName(propertyType) {
        let name = uuid();
        if (propertyType === "html") {
            name = `${name}_html`;
        }
        return name;
    }

    /* --------------------------------------------------------
     * Event handlers
     * -------------------------------------------------------- */

    /**
     * Move the given property up or down in the list.
     *
     * @param {string} propertyName
     * @param {string} direction, either "up" or "down"
     */
    async onPropertyMove(propertyName, direction) {
        const propertiesValues = this.propertiesList || [];
        const propertyIndex = propertiesValues.findIndex(
            (property) => property.name === propertyName,
        );

        const targetIndex = propertyIndex + (direction === "down" ? 1 : -1);
        if (targetIndex < 0 || targetIndex >= propertiesValues.length) {
            this.notification.add(
                direction === "down"
                    ? _t("This field is already last")
                    : _t("This field is already first"),
                { type: "warning" },
            );
            return;
        }
        this.state.movedPropertyName = propertyName;

        const prop = propertiesValues[targetIndex];
        propertiesValues[targetIndex] = propertiesValues[propertyIndex];
        propertiesValues[propertyIndex] = prop;
        propertiesValues[propertyIndex].definition_changed = true;

        await this.props.record.update({ [this.props.name]: propertiesValues });
        await this._unfoldPropertyGroup(targetIndex, propertiesValues);

        // move the popover once the DOM is updated
        this.movePopoverToProperty = propertyName;
    }

    /**
     * Move a property after the target property.
     *
     * @param {string} propertyName
     * @param {string} toPropertyName, the target property
     *  (null if we move the property to the first index)
     */
    async onPropertyMoveTo(propertyName, toPropertyName, moveBefore) {
        const propertiesValues = this.propertiesList || [];

        let fromIndex = propertiesValues.findIndex(
            (property) => property.name === propertyName,
        );
        let toIndex = propertiesValues.findIndex(
            (property) => property.name === toPropertyName,
        );
        const columnSize = Math.ceil(
            propertiesValues.length / this.renderedColumnsCount,
        );

        // Create separators to preserve the initial column split, but only
        // when moving across columns (moving inside the same column is a no-op).
        if (
            this.renderedColumnsCount > 1 &&
            !propertiesValues.some(
                (p, index) => index !== 0 && p.type === "separator",
            ) &&
            Math.floor(fromIndex / columnSize) !== Math.floor(toIndex / columnSize)
        ) {
            // Unfold the separators directly on the local copy (`value: false`):
            // `_toggleSeparators` would re-read the record data, which doesn't
            // contain the spliced separators yet.
            const newSeparators = [];
            for (let col = 0; col < this.renderedColumnsCount; ++col) {
                const separatorIndex = columnSize * col + newSeparators.length;

                if (propertiesValues[separatorIndex]?.type === "separator") {
                    propertiesValues[separatorIndex].value = false;
                    newSeparators.push(propertiesValues[separatorIndex].name);
                    continue;
                }
                const newSeparator = {
                    type: "separator",
                    string: _t("Group %s", col + 1),
                    name: this.generatePropertyName("separator"),
                    value: false,
                };
                newSeparators.push(newSeparator.name);
                propertiesValues.splice(separatorIndex, 0, newSeparator);
            }
            toPropertyName = toPropertyName || propertiesValues.at(-1).name;

            // indexes might have changed
            fromIndex = propertiesValues.findIndex(
                (property) => property.name === propertyName,
            );
            toIndex = propertiesValues.findIndex(
                (property) => property.name === toPropertyName,
            );
        }

        if (moveBefore) {
            toIndex--;
        }
        if (toIndex < fromIndex) {
            // the first splice operation will change the index
            toIndex++;
        }
        propertiesValues.splice(toIndex, 0, propertiesValues.splice(fromIndex, 1)[0]);
        propertiesValues[0].definition_changed = true;
        this.props.record.update({ [this.props.name]: propertiesValues });
    }

    /**
     * Move a group of properties after the target group.
     *
     * @param {string} propertyName
     * @param {string} toPropertyName, the target group (separator)
     *  (null if we move the group to the first index)
     */
    onGroupMoveTo(propertyName, toPropertyName) {
        const propertiesValues = this.propertiesList || [];
        const fromIndex = propertiesValues.findIndex(
            (property) => property.name === propertyName,
        );
        const toIndex = propertiesValues.findIndex(
            (property) => property.name === toPropertyName,
        );
        if (
            propertiesValues[fromIndex].type !== "separator" ||
            (toIndex >= 0 && propertiesValues[toIndex].type !== "separator")
        ) {
            throw new Error("Something went wrong");
        }

        const getNextSeparatorIndex = (startIndex) => {
            const nextSeparatorIndex = propertiesValues.findIndex(
                (property, index) =>
                    property.type === "separator" && index > startIndex,
            );
            return nextSeparatorIndex < 0
                ? propertiesValues.length
                : nextSeparatorIndex;
        };
        const groupSize = getNextSeparatorIndex(fromIndex) - fromIndex;
        let targetIndex = getNextSeparatorIndex(toIndex);
        if (targetIndex > fromIndex) {
            // the size of the array will change after the first splice
            // so we need to correct the index
            targetIndex -= groupSize;
        }
        propertiesValues.splice(
            targetIndex,
            0,
            ...propertiesValues.splice(fromIndex, groupSize),
        );
        propertiesValues[0].definition_changed = true;
        this.props.record.update({ [this.props.name]: propertiesValues });
    }

    /**
     * The value / definition of the given property has been changed.
     * `propertyValue` contains the definition of the property with the value.
     *
     * @param {string} propertyName
     * @param {object} propertyValue
     */
    onPropertyValueChange(propertyName, propertyValue) {
        const propertiesValues = this.propertiesList;
        propertiesValues.find((property) => property.name === propertyName).value =
            propertyValue;
        this.props.record.update({ [this.props.name]: propertiesValues });
    }

    /**
     * Check if the definition is not already opened
     * and if it's not the case, open the popover with the property definition.
     *
     * @param {MouseEvent} event
     * @param {string} propertyName
     */
    async onPropertyEdit(event, propertyName) {
        event.stopPropagation();
        event.preventDefault();
        const target = /** @type {HTMLElement} */ (event.target);
        if (target.classList.contains("disabled")) {
            // remove the glitch if we click on the edit button
            // while the popover is already opened
            return;
        }

        target.classList.add("disabled");
        this._openPropertyDefinition(target, propertyName, false);
    }

    /**
     * The property definition or value has been changed.
     *
     * @param {object} propertyDefinition
     */
    async onPropertyDefinitionChange(propertyDefinition) {
        propertyDefinition["definition_changed"] = true;
        if (propertyDefinition.type === "separator") {
            // remove all other keys
            const separatorKeys = new Set([
                "definition_changed",
                "fold_by_default",
                "name",
                "string",
                "type",
                "value",
            ]);
            // remove all other keys in place, since propertyDefinition instance
            // will be used as a PropertyDefinition component state value.
            for (const key of Object.keys(propertyDefinition)) {
                if (!separatorKeys.has(key)) {
                    delete propertyDefinition[key];
                }
            }
        }
        const propertiesValues = this.propertiesList;
        const propertyIndex = this._getPropertyIndex(propertyDefinition.name);

        const oldType = propertiesValues[propertyIndex].type;
        const newType = propertyDefinition.type;

        this._regeneratePropertyName(
            propertyDefinition,
            propertiesValues[propertyIndex],
        );

        propertiesValues[propertyIndex] = propertyDefinition;
        await this.props.record.update({ [this.props.name]: propertiesValues });

        if (newType === "separator" && oldType !== "separator") {
            // unfold automatically the new separator
            await this._toggleSeparators(
                [propertyDefinition.name],
                propertyDefinition.fold_by_default,
            );
            // layout has been changed, move the definition popover
            this.movePopoverToProperty = propertyDefinition.name;
        } else if (oldType === "separator" && newType !== "separator") {
            // unfold automatically the previous separator
            const previousSeperator = propertiesValues.findLast(
                (property, index) =>
                    index < propertyIndex && property.type === "separator",
            );
            if (previousSeperator) {
                await this._toggleSeparators(
                    [previousSeperator.name],
                    propertyDefinition.fold_by_default,
                );
            }
            // layout has been changed, move the definition popover
            this.movePopoverToProperty = propertyDefinition.name;
        }
    }

    /**
     * Mark a property as "to delete".
     *
     * @param {string} propertyName
     */
    onPropertyDelete(propertyName) {
        let message = _t("Are you sure you want to delete this property field?") + " ";
        if (this.definitionRecordModel !== "properties.base.definition") {
            const parentName =
                this.props.record.data[this.definitionRecordField].display_name;
            const parentFieldLabel =
                this.props.record.fields[this.definitionRecordField].string;
            message += _t(
                'It will be removed for everyone using the "%(parentName)s" %(parentFieldLabel)s.',
                { parentName, parentFieldLabel },
            );
        } else {
            message += _t("It will be removed for everyone!");
        }
        this.popover.close();
        const dialogProps = {
            title: _t("Delete Property Field"),
            body: message,
            confirmLabel: _t("Delete Field"),
            cancelLabel: _t("Discard"),
            confirm: () => {
                const propertiesDefinitions = this.propertiesList;
                propertiesDefinitions.find(
                    (property) => property.name === propertyName,
                ).definition_deleted = true;
                this.props.record.update({
                    [this.props.name]: propertiesDefinitions,
                });
            },
            cancel: () => {},
        };
        this.dialogService.add(ConfirmationDialog, dialogProps);
    }

    async onPropertyCreate() {
        if (!this.definitionRecordId || !this.definitionRecordModel) {
            this.notification.add(
                _t("Oops! A %(parentFieldLabel)s is needed to add property fields.", {
                    parentFieldLabel:
                        this.props.record.fields[this.definitionRecordField].string,
                }),
                { type: "warning" },
            );
            return;
        }
        const propertiesDefinitions = this.propertiesList || [];

        if (
            propertiesDefinitions.length &&
            propertiesDefinitions.some(
                (prop) =>
                    prop.type !== "separator" && (!prop.string || !prop.string.length),
            )
        ) {
            // do not allow to add new field until we set a label on the previous one
            this.propertiesRef.el
                .closest(".o_field_properties")
                .classList.add("o_field_invalid");

            this.notification.add(
                _t("Please complete your properties before adding a new one"),
                {
                    type: "warning",
                },
            );
            return;
        }
        const count = propertiesDefinitions.length;

        this.propertiesRef.el
            .closest(".o_field_properties")
            .classList.remove("o_field_invalid");

        const newName = this.generatePropertyName("char");
        propertiesDefinitions.push({
            name: newName,
            string: _t("Property %s", count + 1),
            type: "char",
            definition_changed: true,
        });
        this.initialValues[newName] = { name: newName, type: "char" };
        await this.props.record.update({
            [this.props.name]: propertiesDefinitions,
        });
        await this._unfoldPropertyGroup(count - 1, propertiesDefinitions);
        this.openPropertyDefinition = newName;
    }

    /**
     * Fold / unfold the given separator property.
     *
     * @param {string} propertyName, Name of the separator property
     */
    onSeparatorClick(propertyName) {
        if (propertyName) {
            this._toggleSeparators([propertyName]);
        }
    }

    /**
     * Verify that we can write on properties, we can not change the definition
     * if we don't have access for parent or if no parent is set.
     */
    async checkDefinitionWriteAccess() {
        if (!this.definitionRecordId || !this.definitionRecordModel) {
            return false;
        }

        return await user.checkAccessRight(
            this.definitionRecordModel,
            "write",
            this.definitionRecordId,
        );
    }

    /**
     * The tags list has been changed.
     * If `newValue` is given, update the property value as well.
     *
     * @param {string} propertyName
     * @param {array} newTags
     * @param {array | null} newValue
     */
    onTagsChange(propertyName, newTags, newValue = null) {
        const propertyDefinition = this.propertiesList.find(
            (property) => property.name === propertyName,
        );
        propertyDefinition.tags = newTags;
        if (newValue !== null) {
            propertyDefinition.value = newValue;
        }
        propertyDefinition.definition_changed = true;
        this.onPropertyDefinitionChange(propertyDefinition);
    }

    /* --------------------------------------------------------
     * Private methods
     * -------------------------------------------------------- */

    /**
     * Recompute `state.canChangeDefinition` / `state.isInEditMode` against
     * the given props. Single implementation for every edit-mode transition
     * (mount, cog-menu edit, definition record change, props update).
     *
     * @param {object} [props=this.props]
     * @param {object} [options]
     * @param {boolean} [options.recheck=false] force a fresh write-access
     *  check instead of reusing a previously granted one (e.g. when the
     *  definition record changed)
     * @param {boolean} [options.force=false] enter edit mode regardless of
     *  the current state / `editMode` prop (e.g. explicit user action)
     * @returns {Promise<boolean>} whether edit mode is active
     */
    async _recomputeEditMode(
        props = this.props,
        { recheck = false, force = false } = {},
    ) {
        let canChangeDefinition = !recheck && this.state.canChangeDefinition;
        if (!canChangeDefinition) {
            canChangeDefinition = await this.checkDefinitionWriteAccess();
        }
        this.state.canChangeDefinition = !!canChangeDefinition;
        this.state.isInEditMode =
            !!canChangeDefinition &&
            !props.readonly &&
            (force || this.state.isInEditMode || !!props.editMode);
        return this.state.isInEditMode;
    }

    /**
     * Switch the folded state of the given separators.
     *
     * @param {array} separatorNames, list of separator name to fold / unfold
     * @param {boolean} [forceState] force the separator to be folded or open
     */
    _toggleSeparators(separatorNames, forceState) {
        const propertiesValues = this.propertiesList;
        for (const separatorName of separatorNames) {
            const property = propertiesValues.find(
                (prop) => prop.name === separatorName,
            );
            if (property) {
                property.value =
                    forceState ?? !(property.value ?? property.fold_by_default);
            }
        }
        return this.props.record.update({
            [this.props.name]: propertiesValues,
        });
    }

    /**
     * Move the popover to the given property id, used when the position of
     * properties changes. Runs after the DOM update (see the useEffect below).
     */
    _movePopoverIfNeeded() {
        if (!this.movePopoverToProperty) {
            return;
        }
        const propertyName = this.movePopoverToProperty;
        this.movePopoverToProperty = null;

        const popoverContent = document.querySelector(".o_field_property_definition");
        const popover = popoverContent?.closest(".o_popover");
        const target = document.querySelector(
            `*[property-name="${propertyName}"] .o_field_property_open_popover`,
        );

        if (!popover || !target) {
            return;
        }

        reposition(
            /** @type {HTMLElement} */ (popover),
            /** @type {HTMLElement} */ (target),
            { position: "top", margin: 10 },
        );
    }

    /**
     * Regenerate the property name if the type/comodel changed (so children
     * reset), or restore the original name otherwise (see
     * _saveInitialPropertiesValues).
     *
     * @param {object} newDefinition
     * @param {object} oldDefinition
     */
    _regeneratePropertyName(newDefinition, oldDefinition) {
        const initialValues = this.initialValues[newDefinition.name];
        if (
            initialValues &&
            newDefinition.type === initialValues.type &&
            newDefinition.comodel === initialValues.comodel
        ) {
            // restore the original name (so the value on other records are not set to false)
            newDefinition.name = initialValues.name;
        } else if (
            oldDefinition.type !== newDefinition.type ||
            // Definitions carry the target relation as ``comodel`` (see the
            // ``comodel`` branch above and propertiesValues.comodel). ``.model``
            // is always undefined here, so a comodel change (e.g. m2o retargeted
            // to another model) never reset values on other records.
            oldDefinition.comodel !== newDefinition.comodel
        ) {
            // Regenerate the name so other records' stale values (keyed by
            // the old name) are ignored; keep the mapping to restore it later.
            const newName = this.generatePropertyName(newDefinition.type);
            this.initialValues[newName] = initialValues;
            newDefinition.name = newName;
        }
    }

    /**
     * Find the index of the given property, resolving through name
     * regeneration if the type/model changed (see _regeneratePropertyName).
     *
     * @params {string} propertyName
     * @returns {integer}
     */
    _getPropertyIndex(propertyName) {
        const initialName = this.initialValues[propertyName]?.name || propertyName;
        return this.propertiesList.findIndex((property) =>
            [propertyName, initialName].includes(property.name),
        );
    }

    /**
     * Save the original property values so a type/model change can later
     * be discarded (even after save) and the original name restored (see
     * _regeneratePropertyName).
     */
    _saveInitialPropertiesValues() {
        this.initialValues = {};
        for (const propertiesValues of this.props.record.data[this.props.name] || []) {
            this.initialValues[propertiesValues.name] = {
                name: propertiesValues.name,
                type: propertiesValues.type,
                comodel: propertiesValues.comodel,
            };
        }
    }

    /**
     * Open the popover with the property definition.
     *
     * @param {Element} target
     * @param {string} propertyName
     * @param {boolean} isNewlyCreated
     */
    _openPropertyDefinition(target, propertyName, isNewlyCreated = false) {
        const propertiesList = this.propertiesList;
        const propertyIndex = propertiesList.findIndex(
            (property) => property.name === propertyName,
        );

        // maybe the property has been renamed because the type / model
        // changed, retrieve the new one
        const currentName = (propertyName) => {
            const propertiesList = this.propertiesList;
            for (const [newName, initialValue] of Object.entries(this.initialValues)) {
                if (initialValue.name === propertyName) {
                    const prop = propertiesList.find((prop) => prop.name === newName);
                    if (prop) {
                        return newName;
                    }
                }
            }
            return propertyName;
        };

        this.onCloseCurrentPopover = () => {
            this.onCloseCurrentPopover = null;
            this.state.movedPropertyName = null;
            target.classList.remove("disabled");
            if (isNewlyCreated) {
                this._setDefaultPropertyValue(currentName(propertyName));
            }
        };

        this.popover.open(/** @type {HTMLElement} */ (target), {
            fieldName: this.props.name,
            readonly: this.props.readonly || !this.state.canChangeDefinition,
            canChangeDefinition: this.state.canChangeDefinition,
            propertyDefinition: this.propertiesList.find(
                (property) => property.name === currentName(propertyName),
            ),
            context: this.props.context,
            onChange: this.onPropertyDefinitionChange.bind(this),
            onDelete: () => this.onPropertyDelete(currentName(propertyName)),
            onPropertyMove: (direction) =>
                this.onPropertyMove(currentName(propertyName), direction),
            isNewlyCreated: isNewlyCreated,
            propertyIndex: propertyIndex,
            propertiesSize: propertiesList.length,
            record: this.props.record,
            ...this.additionalPropertyDefinitionProps,
        });
    }

    /**
     * Write the default value on the given property.
     *
     * @param {string} propertyName
     */
    _setDefaultPropertyValue(propertyName) {
        const propertiesValues = this.propertiesList;
        const newProperty = propertiesValues.find(
            (property) => property.name === propertyName,
        );
        if (newProperty.default) {
            newProperty.value = newProperty.default;
        }
        this.props.record.update({ [this.props.name]: propertiesValues });
    }

    /**
     * Unfold the group of the given property.
     *
     * @param {integer} targetIndex
     * @param {object} propertiesValues
     */
    _unfoldPropertyGroup(targetIndex, propertiesValues) {
        const separator = propertiesValues.findLast(
            (property, index) => property.type === "separator" && index <= targetIndex,
        );
        if (separator) {
            return this._toggleSeparators([separator.name], false);
        }
    }

    /**
     * Returns the text for the warning raised in the "PROPERTY_FIELD:EDIT"
     * bus event, if the PropertiesField component cannot enter edit mode.
     */
    _getPropertyEditWarningText() {
        if (!this.definitionRecordId) {
            return _t(
                "Oops! A %(parentFieldLabel)s is needed to add property fields.",
                {
                    parentFieldLabel:
                        this.props.record.fields[this.definitionRecordField].string,
                },
            );
        }
        return _t('Oops! You cannot edit the %(parentFieldLabel)s "%(parentName)s".', {
            parentName: this.props.record.data[this.definitionRecordField].display_name,
            parentFieldLabel:
                this.props.record.fields[this.definitionRecordField].string,
        });
    }
}

export const propertiesField = {
    component: PropertiesField,
    displayName: _t("Properties"),
    supportedTypes: ["properties"],
    extractProps({ attrs }, dynamicInfo) {
        return {
            context: dynamicInfo.context,
            columns: Number.parseInt(attrs.columns || "1", 10),
            editMode: exprToBoolean(attrs.editMode),
        };
    },
};

registerField("properties", propertiesField);
