// @ts-check
/** @odoo-module native */

/** @module @web/search/search_favorites_mixin - Favorite (ir.filters) management mixed into SearchModel */

import { RpcEvent } from "@web/core/events";
import { rpcBus } from "@web/core/network/rpc";

import {
    buildIrFilterDescription,
    irFilterToFavorite,
    reconciliateFavorites,
} from "./search_favorites.js";
import { FAVORITE_PRIVATE_GROUP, FAVORITE_SHARED_GROUP } from "./search_state.js";

/**
 * Favorite (``ir.filters``) management for SearchModel: creating/persisting
 * favorites, deriving the ir.filter description of the current query, and
 * reconciling imported favorites against the server records.
 *
 * Mixed into SearchModel (``extends SearchFavoritesMixin(...)``) rather than
 * kept as pass-``this`` module functions so the methods live on the prototype
 * chain: enterprise ``knowledge`` overrides ``_reconciliateFavorites`` to a
 * no-op and reaches it via the class, and every internal call routes through
 * ``this`` so such overrides are honoured. Query-item state (``searchItems``,
 * ``query``, ``nextId``/``nextGroupId``), the domain/context/groupBy builders,
 * ``clearQuery``, ``_createGroupOfSearchItems`` and ``_notify`` live on
 * SearchModel and are reached via ``this``.
 *
 * @template {new (...args: any[]) => any} T
 * @param {T} Base
 */
export const SearchFavoritesMixin = (Base) =>
    class extends Base {
        /**
         * Create a new filter of type 'favorite' and activate it.
         * @param {Object} params
         * @returns {Promise<number>} the server-side ir.filters id
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
            this._notify();
            return serverSideId;
        }

        /** Create an ir.filters record on the server. */
        async _createIrFilters(irFilter) {
            const serverSideIds = await this.orm.call("ir.filters", "create_filter", [
                irFilter,
            ]);
            rpcBus.trigger(RpcEvent.CLEAR_CACHES, "get_views");
            return serverSideIds[0];
        }

        /** The ir.filter payload for the current query (used to persist a favorite). */
        getIrFilterValues(params) {
            const { irFilter } = this._getIrFilterDescription(params);
            return irFilter;
        }

        /** The pre-favorite descriptor for the current query (context/groupBys/orderBy). */
        getPreFavoriteValues(params) {
            const { preFavorite } = this._getIrFilterDescription(params);
            return preFavorite;
        }

        /**
         * Build both the pre-favorite descriptor and the ir.filter payload that
         * capture the current query's context, domain, groupBy and orderBy.
         * @param {Object} [params]
         */
        _getIrFilterDescription(params = {}) {
            const { description, isDefault, isShared, embeddedActionId } = params;
            const fns = this.env.__getContext__.callbacks;
            const localContext = Object.assign({}, ...fns.map((fn) => fn()));
            const gs = this.env.__getOrderBy__.callbacks;
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
         * Turn loaded ir.filters into favorite search items, returning the id of
         * the default favorite (if any).
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

        /** Convert an ir.filter record into a favorite search item. */
        _irFilterToFavorite(irFilter) {
            return irFilterToFavorite(irFilter, this.searchViewFields);
        }

        /**
         * Reconciliate the search items with the ir.filters.
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
            // Replacing/removing favorites in place invalidates the enrichment
            // memo, and `_createGroupOfSearchItems` only clears it when there is
            // at least one NEW favorite to create.
            this._enrichedSearchItems = null;
        }
    };
