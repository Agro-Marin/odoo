// @ts-check
/** @odoo-module native */

/** @module @web/components/record_selectors/base_record_selector */

import { Component, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { KeepLast } from "@web/core/utils/concurrency";
import { useService } from "@web/core/utils/hooks";
export class BaseRecordSelector extends Component {
    /** @type {KeepLast<any>} */
    keepLast;
    /** @type {import("services").ServiceFactories["name"]} */
    nameService;

    setup() {
        this.nameService = useService("name");
        this.keepLast = new KeepLast();
        onWillStart(() => this.computeDerivedParams());
        onWillUpdateProps((nextProps) => this.computeDerivedParams(nextProps));
    }

    /** @returns {boolean} */
    get isAvatarModel() {
        return [
            "res.partner",
            "res.users",
            "hr.employee",
            "hr.employee.public",
        ].includes(this.props.resModel);
    }

    /**
     * @param {Record<string, any>} [props]
     */
    async computeDerivedParams(props = this.props) {
        const displayNames = await this.keepLast.add(this.getDisplayNames(props));
        this.applyDisplayNames(props, displayNames);
    }

    /**
     * @param {Record<string, any>} props
     * @returns {Promise<Record<number, string>>}
     */
    async getDisplayNames(props) {
        const ids = this.getIds(props);
        return this.nameService.loadDisplayNames(props.resModel, ids);
    }

    /**
     * @param {Record<string, any>} [props]
     * @returns {number[]}
     */
    getIds(props = this.props) {
        return [];
    }

    /**
     * @param {Record<string, any>} props
     * @param {Record<number, string>} displayNames
     */
    applyDisplayNames(props, displayNames) {}
}
