// @ts-check
/** @odoo-module native */

/** @module @web/webclient/switch_company_menu/company_selector - Draft company selection model behind the switcher (toggle/login-to, cascading, apply) */

import { router } from "@web/core/browser/router";
import { symmetricalDifference } from "@web/core/utils/collections/arrays";
import { user } from "@web/services/user";

/**
 * id -> company index over ``user.allowedCompaniesWithAncestors``, so a lookup
 * is O(1) instead of an ``Array.find`` per child, per node, per keystroke while
 * filtering.
 *
 * Keyed by the companies ARRAY, not stored in a module-level slot: `user.js`
 * builds a fresh array whenever the user is (re)built, so a new array is
 * exactly the moment the index must be rebuilt. A WeakMap expresses that
 * directly and lets the old index be collected, instead of a pair of mutable
 * module globals compared by hand — which outlived every component and had to
 * be reasoned about per call site.
 *
 * @type {WeakMap<object[], Map<number, any>>}
 */
const indexByCompanies = new WeakMap();

/**
 * @param {number} cid - company ID
 * @returns {Object | undefined} the company descriptor from
 *  ``user.allowedCompaniesWithAncestors``
 */
export function getCompany(cid) {
    const companies = user.allowedCompaniesWithAncestors;
    let index = indexByCompanies.get(companies);
    if (!index) {
        index = new Map(companies.map((c) => [c.id, c]));
        indexByCompanies.set(companies, index);
    }
    return index.get(cid);
}

/**
 * Manages the DRAFT selection state for company switching.
 *
 * Holds the pending set of company ids while the dropdown is open — nothing is
 * applied until {@link apply} runs (on Confirm, or immediately for "log into").
 * Closing without confirming calls {@link reset}, which re-seeds from the
 * currently active companies, so a draft can never leak into a later confirm.
 *
 * Selection cascades down the company tree: selecting or deselecting a parent
 * does the same to its descendants, matching what the per-item checkboxes do.
 */
export class CompanySelector {
    constructor(actionService, dropdownState) {
        this.actionService = actionService;
        this.dropdownState = dropdownState;
        this.selectedCompaniesIds = user.activeCompanies.map((c) => c.id);
    }

    get hasSelectionChanged() {
        return (
            symmetricalDifference(
                this.selectedCompaniesIds,
                user.activeCompanies.map((c) => c.id),
            ).length > 0
        );
    }

    isCompanySelected(companyId) {
        return this.selectedCompaniesIds.includes(companyId);
    }

    /**
     * @param {"toggle"|"loginto"} mode
     * @param {number} companyId
     */
    switchCompany(mode, companyId) {
        if (mode === "toggle") {
            if (this.selectedCompaniesIds.includes(companyId)) {
                this._deselectCompany(companyId);
            } else {
                this._selectCompany(companyId);
            }
        } else if (mode === "loginto") {
            if (this._isSingleCompanyMode()) {
                this.selectedCompaniesIds.splice(0, this.selectedCompaniesIds.length);
            }
            this._selectCompany(companyId, true);
            this.apply();

            this.dropdownState.close?.();
        }
    }

    async apply() {
        // Snapshot the selection: closing the dropdown (loginto/confirm close
        // right after calling apply) runs reset(), which re-seeds
        // selectedCompaniesIds — this must not change under the await below.
        const newCompanyIds = [...this.selectedCompaniesIds];

        // Decide whether the current record survives the switch BEFORE mutating
        // any global state, probing access under the NEW companies (passed
        // explicitly, uncached). The old code switched the cookie/context
        // FIRST and then awaited this RPC: during that window the live UI still
        // showed the old records but every new RPC (autosave, onchange, polling)
        // ran under the new allowed_company_ids — a create/write could land with
        // the wrong company. Checking first keeps the state consistent until the
        // atomic mutate+reload below (and a stalled probe now leaves the old
        // state intact rather than a half-switched one).
        const controller = this.actionService.currentController;
        let dropRecord = false;
        if (controller?.props.resId && controller?.props.resModel) {
            try {
                const hasReadRights = await user.checkAccessRight(
                    controller.props.resModel,
                    "read",
                    controller.props.resId,
                    {
                        context: {
                            ...user.context,
                            allowed_company_ids: newCompanyIds,
                        },
                    },
                );
                dropRecord = !hasReadRights;
            } catch {
                // Keep the current view and let the server enforce access on
                // reload — the switch must still proceed.
            }
        }

        // Mutate cookie/context and reload in ONE synchronous block — no await
        // in between, so there is no window for the still-live UI to issue RPCs
        // under the new context.
        user.activateCompanies(newCompanyIds, {
            includeChildCompanies: false,
            reload: false,
        });
        const state = {};
        // sync: the cookie/context are switched, so the reload must fire
        // immediately — a debounced push could be dropped by a popstate or
        // cancelPushes, leaving a switched cookie under a stale webclient.
        const options = { reload: true, sync: true };
        if (dropRecord) {
            options.replace = true;
            state.actionStack = router.current.actionStack?.slice(0, -1) || [];
        }
        router.pushState(state, options);
    }

    reset() {
        this.selectedCompaniesIds = user.activeCompanies.map((c) => c.id);
    }

    toggleSelectAll(companyIds) {
        // Disallowed companies (e.g. ancestors only shown for the tree
        // structure) can never be activated: selecting them would render
        // their checkbox checked and show Confirm for a no-op switch.
        const allowedCompanyIds = companyIds.filter((id) => this._isCompanyAllowed(id));
        const anySelected = allowedCompanyIds.some((id) =>
            this.selectedCompaniesIds.includes(id),
        );

        if (anySelected) {
            // If any company is selected, unselect all of them, cascading
            // to their child companies as the per-item checkboxes do.
            for (const companyId of allowedCompanyIds) {
                if (this.selectedCompaniesIds.includes(companyId)) {
                    this._deselectCompany(companyId);
                }
            }
        } else {
            // Go through _selectCompany so the selection cascades to child
            // companies (possibly filtered out of view), exactly as the
            // per-item checkboxes do; it also dedupes already-selected ids.
            for (const companyId of allowedCompanyIds) {
                this._selectCompany(companyId);
            }
        }
    }

    _selectCompany(companyId, unshift = false) {
        if (this._isCompanyAllowed(companyId)) {
            if (!this.selectedCompaniesIds.includes(companyId)) {
                if (unshift) {
                    this.selectedCompaniesIds.unshift(companyId);
                } else {
                    this.selectedCompaniesIds.push(companyId);
                }
            } else if (unshift) {
                const index = this.selectedCompaniesIds.findIndex(
                    (c) => c === companyId,
                );
                this.selectedCompaniesIds.splice(index, 1);
                this.selectedCompaniesIds.unshift(companyId);
            }
        }

        this._getBranches(companyId).forEach((companyId) =>
            this._selectCompany(companyId),
        );
    }

    _deselectCompany(companyId) {
        if (this.selectedCompaniesIds.includes(companyId)) {
            this.selectedCompaniesIds.splice(
                this.selectedCompaniesIds.indexOf(companyId),
                1,
            );
        }
        this._getBranches(companyId).forEach((companyId) =>
            this._deselectCompany(companyId),
        );
    }

    /**
     * The child companies of ``companyId``, as ids.
     *
     * ``getCompany`` is dereferenced without a guard, and that is safe because
     * of a SERVER-side invariant: ``ir_http.py``'s ``_get_company_hierarchy``
     * clips every ``child_ids`` to the ids it actually returns
     * (``children_in_hierarchy``), across both ``allowed_companies`` and
     * ``disallowed_ancestor_companies``. So a child id reached from here is
     * always present in ``allowedCompaniesWithAncestors``. If that server
     * behaviour ever changes, this recursion is the first thing that breaks —
     * with a bare ``TypeError`` on an undefined company.
     *
     * @param {number} companyId
     * @returns {number[]}
     */
    _getBranches(companyId) {
        return getCompany(companyId).child_ids || [];
    }

    _isCompanyAllowed(companyId) {
        return user.allowedCompanies.some((c) => c.id === companyId);
    }

    _isSingleCompanyMode() {
        if (this.selectedCompaniesIds.length === 1) {
            return true;
        }

        const getActiveCompany = (companyId) => {
            const isActive = this.selectedCompaniesIds.includes(companyId);
            return isActive ? getCompany(companyId) : null;
        };

        let rootCompany = undefined;
        for (const companyId of this.selectedCompaniesIds) {
            let company = getActiveCompany(companyId);
            if (!company) {
                // A selected id that is not in the active-companies map (edge
                // case after a company change): skip rather than deref
                // ``company.parent_id`` on null.
                continue;
            }

            // Find the root active parent of the company
            while (getActiveCompany(company.parent_id)) {
                company = getActiveCompany(company.parent_id);
            }

            if (rootCompany === undefined) {
                rootCompany = company;
            } else if (rootCompany !== company) {
                return false;
            }
        }

        // If some children or sub-children of the root company
        // are not active, we are in multi-company mode.
        if (rootCompany?.child_ids) {
            const queue = [...rootCompany.child_ids];
            while (queue.length) {
                const company = getActiveCompany(queue.pop());
                if (company?.child_ids) {
                    queue.push(...company.child_ids);
                } else if (!company) {
                    return false;
                }
            }
        }

        return true;
    }
}
