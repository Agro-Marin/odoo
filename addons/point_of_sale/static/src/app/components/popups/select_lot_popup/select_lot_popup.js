/** @odoo-module native */
import { Component, onMounted, useState } from "@odoo/owl";
import { useAutoFocusToLast } from "@point_of_sale/app/hooks/hooks";
import { AutoComplete } from "@web/components/autocomplete";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { _t } from "@web/core/translation";
import { useChildRef, useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/ui/dialog";
const log = makeLogger("pos.popup.lots");
export class SelectLotPopup extends Component {
    static template = "point_of_sale.SelectLotPopup";
    static components = { Dialog, AutoComplete };
    static props = {
        array: Array,
        isSingleItem: Boolean,
        title: String,
        name: String,
        getPayload: Function,
        close: Function,
        options: { type: Array, optional: true },
        customInput: { type: Boolean, optional: true },
        uniqueValues: { type: Boolean, optional: true },
        isLotNameUsed: { type: Function, optional: true },
    };

    setup() {
        useLifecycleLog(log);
        this._id = 0;
        log.lifecycle("opened", () => ({
            product: this.props.name,
            isSingleItem: this.props.isSingleItem,
            existing: this.props.array.length,
            options: this.props.options?.length ?? 0,
            customInput: Boolean(this.props.customInput),
            uniqueValues: Boolean(this.props.uniqueValues),
        }));
        this.state = useState({
            value: this.props.isSingleItem ? this.props.array[0]?.text : "",
            values: this.props.array
                .filter((item) => item.text.trim() !== "")
                .map((item) => ({
                    text: item.text.trim(),
                    id: item.id,
                })),
        });
        useAutoFocusToLast();
        this.notification = useService("notification");
        this.inputRef = useChildRef();
        onMounted(() => {
            this.inputRef.el.click();
        });
    }
    _nextId() {
        return this._id++;
    }
    getSources() {
        return [
            {
                options: (currentInput) => {
                    const filteredOptions = this.props.options.filter(
                        (option) =>
                            option.name.includes(currentInput) &&
                            !this.state.values.some(
                                (value) => value.text === option.name,
                            ),
                    );
                    if (filteredOptions.length) {
                        return filteredOptions.map((option) => ({
                            label: option.name,
                            onSelect: () =>
                                this.onSelect({
                                    create: true,
                                    id: option.id,
                                    label: option.name,
                                }),
                        }));
                    } else if (this.props.customInput && currentInput) {
                        const label = _t("Create Lot/Serial number...");
                        return [
                            {
                                label,
                                onSelect: () =>
                                    this.onSelect({
                                        create: true,
                                        currentInput,
                                        id: currentInput,
                                        label,
                                    }),
                            },
                        ];
                    } else {
                        return [
                            {
                                label: _t("No existing Lot/Serial number found..."),
                                onSelect: () => this.onSelect({ create: false }),
                            },
                        ];
                    }
                },
            },
        ];
    }
    onSelect(lot) {
        log.logic("onSelect", () => ({
            create: lot.create,
            fromInput: Boolean(lot.currentInput),
            id: lot.id,
            duplicate: this.state.values.some((item) => item.text === lot.currentInput),
        }));
        if (this.state.values.some((item) => item.text === lot.currentInput)) {
            return this.notification.add(
                _t("The Lot/Serial number is already added."),
                {
                    type: "warning",
                    sticky: false,
                },
            );
        }
        if (!lot.create) {
            return this.notification.add(_t("The Lot/Serial number is not valid"), {
                type: "warning",
                sticky: false,
            });
        }
        const newItem = lot.currentInput
            ? { text: lot.currentInput, id: lot.id }
            : { text: lot.label, id: lot.id };
        this.state.values = this.props.isSingleItem
            ? [newItem]
            : [...this.state.values, newItem];
        this.state.value = this.props.isSingleItem ? newItem.text : "";
    }
    removeItem(id) {
        this.state.values = this.state.values.filter((item) => item.id !== id);
    }
    confirm() {
        const validItems = this.state.values.filter((item) => {
            const itemValue = item.text.trim();
            return (
                itemValue !== "" &&
                !this.props.isLotNameUsed(itemValue) &&
                (this.props.customInput ||
                    this.props.options.map((o) => o.name).includes(itemValue) ||
                    this.props.array.some((i) => i.text === itemValue))
            );
        });
        const filteredValues = this.props.uniqueValues
            ? [...new Map(validItems.map((item) => [item.text.trim(), item])).values()]
            : validItems;
        const result = filteredValues.map((item) => {
            const matchingLot = this.props.array.find((lot) => lot.text === item.text);
            return {
                text: item.text,
                _id: this._nextId(),
                ...(matchingLot ? { id: matchingLot.id } : {}),
            };
        });
        log.pipeline("confirm", () => ({
            product: this.props.name,
            entered: this.state.values.length,
            valid: validItems.length,
            deduplicated: validItems.length - filteredValues.length,
            existing: result.filter((r) => r.id).length,
            new: result.filter((r) => !r.id).length,
        }));
        this.props.getPayload(result);
        this.props.close();
    }
    close() {
        this.props.close();
    }
    onKeyDown(event) {
        if (event.key === "Enter" && this.state.values.length) {
            event.stopPropagation();
            this.confirm();
        }
    }
}
