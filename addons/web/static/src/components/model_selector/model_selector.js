// @ts-check
/** @odoo-module native */

import { Component, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { AutoComplete } from "@web/components/autocomplete/autocomplete";
import { _t } from "@web/core/translation";
import { KeepLast, SupersededError } from "@web/core/utils/concurrency";
import { useService } from "@web/core/utils/hooks";
import { fuzzyLookup } from "@web/core/utils/search";

const DEFAULT_VISIBLE_MODELS = 8;

export class ModelSelector extends Component {
    static template = "web.ModelSelector";
    static components = { AutoComplete };
    static props = {
        onModelSelected: Function,
        id: { type: String, optional: true },
        value: { type: String, optional: true },
        placeholder: { type: String, optional: true },
        models: { type: Array, optional: true },
        nbVisibleModels: { type: Number, optional: true },
        autofocus: { type: Boolean, optional: true },
        autoSelect: { type: Boolean, optional: true },
    };

    /** @type {import("services").ServiceFactories["orm"]} */
    orm;
    /** @type {KeepLast<any>} */
    keepLast;
    /**
     * @type {Object[]}
     */
    models = [];
    /**
     * @type {{ placeholder: string, options: Function }[]}
     */
    sources;

    setup() {
        this.orm = useService("orm");
        this.keepLast = new KeepLast({ rejectSuperseded: true });
        this.sources = [
            {
                placeholder: _t("Loading..."),
                options: this.loadOptionsSource.bind(this),
            },
        ];

        onWillStart(() => this.loadModels(this.props));
        onWillUpdateProps((nextProps) => {
            if (nextProps.models !== this.props.models) {
                return this.loadModels(nextProps);
            }
        });
    }

    /**
     * @param {Record<string, any>} props
     * @returns {Promise<void>}
     */
    async loadModels(props) {
        let records;
        try {
            records = await this.keepLast.add(
                props.models
                    ? this.orm.call("ir.model", "display_name_for", [props.models])
                    : this.fetchAvailableModels(),
            );
        } catch (error) {
            if (error instanceof SupersededError) {
                return;
            }
            throw error;
        }

        this.models = records.map((/** @type {any} */ record) => ({
            cssClass: `o_model_selector_${record.model.replaceAll(".", "_")}`,
            data: {
                technical: record.model,
            },
            label: record.display_name,
            onSelect: () =>
                this.props.onModelSelected({
                    label: record.display_name,
                    technical: record.model,
                }),
        }));
    }

    /** @returns {string} */
    get placeholder() {
        return this.props.placeholder || _t("Type a model here...");
    }

    /**
     * @returns {number}
     */
    get nbVisibleModels() {
        return this.props.nbVisibleModels || DEFAULT_VISIBLE_MODELS;
    }

    /**
     * @param {string} name
     * @returns {Object[]}
     */
    filterModels(name) {
        if (!name) {
            const visibleModels = this.models.slice(0, this.nbVisibleModels);
            if (this.models.length - visibleModels.length > 0) {
                visibleModels.push({
                    label: _t("Start typing..."),
                    cssClass: "o_m2o_start_typing",
                });
            }
            return visibleModels;
        }
        return fuzzyLookup(
            name,
            this.models,
            (model) => model.data.technical + model.label,
        );
    }

    /**
     * @param {string} request
     * @returns {Object[]}
     */
    loadOptionsSource(request) {
        const options = this.filterModels(request);

        if (!options.length) {
            options.push({
                label: _t("No records"),
                cssClass: "o_m2o_no_result",
            });
        }
        return options;
    }

    /**
     * @returns {Promise<Array<{model: string, display_name: string}>>}
     */
    async fetchAvailableModels() {
        const result = await this.orm.call("ir.model", "get_available_models");
        return result || [];
    }
}
