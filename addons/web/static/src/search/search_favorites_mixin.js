// @ts-check
/** @odoo-module native */

import { actionContextCallbacks } from "@web/core/action_context_port";

import {
    buildIrFilterDescription,
    irFilterToFavorite,
    reconciliateFavorites,
} from "./search_favorites.js";
import { FAVORITE_PRIVATE_GROUP, FAVORITE_SHARED_GROUP } from "./search_state.js";

/** @import { FavoriteItem } from "./search_types" */

/**
 * @template {new (...args: any[]) => any} T
 * @param {T} Base
 */
export const SearchFavoritesMixin = (Base) =>
    class extends Base {
        /**
         * @param {Record<string, any>} params
         * @returns {Promise<number>}
         */
        async createNewFavorite(params) {
            const { preFavorite, irFilter } = this._getIrFilterDescription(params);
            /** @type {Record<string, any>} */
            const pre = preFavorite;
            const serverSideId = await this._createIrFilters(irFilter);

            this._withNotificationsBlocked(() => {
                this.clearQuery();
                const favorite = {
                    ...preFavorite,
                    type: "favorite",
                    id: this.nextId,
                    groupId: this.nextGroupId,
                    groupNumber:
                        pre.userIds.length === 1
                            ? FAVORITE_PRIVATE_GROUP
                            : FAVORITE_SHARED_GROUP,
                    removable: true,
                    serverSideId,
                };
                this.searchItems[this.nextId] = favorite;
                this.query.push({ searchItemId: this.nextId });
                this.nextGroupId++;
                this.nextId++;
            });
            await this._notify();
            return serverSideId;
        }

        /** @param {Record<string, any>} irFilter */
        async _createIrFilters(irFilter) {
            const serverSideIds = await this.orm.call("ir.filters", "create_filter", [
                irFilter,
            ]);
            return serverSideIds[0];
        }

        /** @param {Record<string, any>} [params] */
        getIrFilterValues(params) {
            const { irFilter } = this._getIrFilterDescription(params);
            return irFilter;
        }

        /** @param {Record<string, any>} [params] */
        getPreFavoriteValues(params) {
            const { preFavorite } = this._getIrFilterDescription(params);
            return preFavorite;
        }

        /**
         * @param {Record<string, any>} [params]
         */
        _getIrFilterDescription(params = {}) {
            const { description, isDefault, isShared, embeddedActionId } = params;
            const fns = actionContextCallbacks(this.env, "__getContext__");
            const localContext = Object.assign({}, ...fns.map((fn) => fn()));
            const gs = actionContextCallbacks(this.env, "__getOrderBy__");
            let localOrderBy;
            if (gs.length) {
                localOrderBy = gs.flatMap((g) => g());
            }
            return buildIrFilterDescription({
                description,
                isDefault,
                isShared,
                embeddedActionId,
                localContext,
                localOrderBy,
                getContext: () => this._getContext(),
                getDomain: () =>
                    this._getDomain({
                        raw: true,
                        withGlobal: false,
                        withSearchPanel: false,
                    }),
                getGroupBy: () => this._getGroupBy(),
                getOrderBy: () => this._getOrderBy(),
                globalContext: this.globalContext,
                actionId: this.env.config.actionId,
                resModel: this.resModel,
            });
        }

        /**
         * @param {Record<string, any>[]} irFilters
         * @returns {number|null}
         */
        _createGroupOfFavorites(irFilters) {
            let defaultFavoriteId = null;
            irFilters.forEach((irFilter) => {
                const favorite = this._irFilterToFavorite(irFilter);
                this._createGroupOfSearchItems([favorite]);
                if (favorite.isDefault) {
                    defaultFavoriteId = favorite.id;
                }
            });
            return defaultFavoriteId;
        }

        /** @param {Record<string, any>} irFilter */
        _irFilterToFavorite(irFilter) {
            return irFilterToFavorite(irFilter, this.searchViewFields);
        }

        _reconciliateFavorites() {
            if (this.irFilters === undefined) {
                return;
            }
            reconciliateFavorites(
                this.searchItems,
                this.query,
                this.irFilters,
                (/** @type {Record<string, any>} */ irFilter) =>
                    this._irFilterToFavorite(irFilter),
                (/** @type {Record<string, any>[]} */ irFilters) =>
                    this._createGroupOfFavorites(irFilters),
            );
            this._enrichedSearchItems = null;
        }
    };
