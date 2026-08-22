// @ts-check
/** @odoo-module native */

import { Component, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { isAvatarModel } from "@web/components/record_selectors/avatar_models";
import { KeepLast, SupersededError } from "@web/core/utils/concurrency";
import { useService } from "@web/core/utils/hooks";
export class BaseRecordSelector extends Component {
    /** @type {KeepLast<any>} */
    keepLast;
    /** @type {import("services").ServiceFactories["name"]} */
    nameService;

    setup() {
        this.nameService = useService("name");
        this.keepLast = new KeepLast({ rejectSuperseded: true });
        onWillStart(() => this.computeDerivedParams());
        onWillUpdateProps((nextProps) => this.computeDerivedParams(nextProps));
    }

    /** @returns {boolean} */
    get isAvatarModel() {
        return isAvatarModel(this.props.resModel);
    }

    /**
     * @param {Record<string, any>} [props]
     */
    async computeDerivedParams(props = this.props) {
        let displayNames;
        try {
            displayNames = await this.keepLast.add(this.getDisplayNames(props));
        } catch (error) {
            if (error instanceof SupersededError) {
                return;
            }
            throw error;
        }
        this.applyDisplayNames(props, displayNames);
    }

    /**
     * @param {Record<string, any>} props
     * @returns {Promise<import("@web/core/name_service").DisplayNames>}
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
