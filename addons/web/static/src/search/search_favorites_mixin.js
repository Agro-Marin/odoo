// @ts-check
/** @odoo-module native */

/** @module @web/search/search_favorites_mixin */

import { actionContextCallbacks } from "@web/core/action_context_port";

import {
    buildIrFilterDescription,
    irFilterToFavorite,
    reconciliateFavorites,
} from "./search_favorites.js";
import { FAVORITE_PRIVATE_GROUP, FAVORITE_SHARED_GROUP } from "./search_state.js";

/**
 * @template {new (...args: any[]) => any} T
 * @param {T} Base
 */
export const SearchFavoritesMixin = (Base) =>
    class extends Base {
        /**
         * @param {Object} params
         * @returns {Promise<number>}
         */
        async createNewFavorite(params) {
            const { preFavorite, irFilter } = this._getIrFilterDescription(params);
            const serverSideId = await this._createIrFilters(irFilter);

            this._withNotificationsBlocked(() => {
                this.clearQuery();
                const favorite = {
                    ...preFavorite,
                    type: "favorite",
                    id: this.nextId,
                    groupId: this.nextGroupId,
                    groupNumber:
                        preFavorite.userIds.length === 1
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

        async _createIrFilters(irFilter) {
            // The get_views cache invalidation for this `create_filter` is owned
            // declaratively by ViewService (which watches ir.filters + this
            // method), so no manual CLEAR_CACHES is fired here.
            const serverSideIds = await this.orm.call("ir.filters", "create_filter", [
                irFilter,
            ]);
            return serverSideIds[0];
        }

        getIrFilterValues(params) {
            const { irFilter } = this._getIrFilterDescription(params);
            return irFilter;
        }

        getPreFavoriteValues(params) {
            const { preFavorite } = this._getIrFilterDescription(params);
            return preFavorite;
        }

        /**
         * @param {Object} [params]
         */
        _getIrFilterDescription(params = {}) {
            const { description, isDefault, isShared, embeddedActionId } = params;
            // Read through the port: these slots are absent outside an action
            // context and `null` where a producer opted out (web_studio nulls
            // all five), and this dereferenced both unguarded.
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
         * @param {Object[]} irFilters
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

        _irFilterToFavorite(irFilter) {
            return irFilterToFavorite(irFilter, this.searchViewFields);
        }

        /**
         * @private
         */
        _reconciliateFavorites() {
            if (this.irFilters === undefined) {
                return;
            }
            reconciliateFavorites(
                this.searchItems,
                this.query,
                this.irFilters,
                (irFilter) => this._irFilterToFavorite(irFilter),
                (irFilters) => this._createGroupOfFavorites(irFilters),
            );
            this._enrichedSearchItems = null;
        }
    };
