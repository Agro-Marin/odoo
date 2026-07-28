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
 * Keyed by the companies ARRAY: `user.js` builds a fresh array whenever the
 * user is (re)built, so a new array is exactly the moment the index must be
 * rebuilt, and the WeakMap lets the old index be collected.
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
 * Allowed-company id set, cached against the array it was built from — same
 * invalidation story as {@link indexByCompanies}.
 *
 * @type {WeakMap<object[], Set<number>>}
 */
const allowedIdsByCompanies = new WeakMap();

/**
 * Whether the user may act on this company.
 *
 * Set-backed rather than an ``Array.some``/``map().includes()`` scan: the
 * ``SwitchCompanyItem`` template reads this five times per company row, on
 * every render of a dropdown that only appears once the user HAS a lot of
 * companies.
 *
 * @param {number} companyId
 * @returns {boolean}
 */
export function isCompanyAllowed(companyId) {
    const companies = user.allowedCompanies;
    let allowedIds = allowedIdsByCompanies.get(companies);
    if (!allowedIds) {
        allowedIds = new Set(companies.map((c) => c.id));
        allowedIdsByCompanies.set(companies, allowedIds);
    }
    return allowedIds.has(companyId);
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
            // Same contract as SwitchCompanyMenu.confirm(): fire-and-forget, but
            // never silently swallow a failure.
            Promise.resolve(this.apply()).catch((error) => {
                console.warn("Failed to apply the company selection", error);
            });

            this.dropdownState.close?.();
        }
    }

    async apply() {
        const newCompanyIds = [...this.selectedCompaniesIds];

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

        user.activateCompanies(newCompanyIds, {
            includeChildCompanies: false,
            reload: false,
        });
        // `activateCompanies` NORMALISES the request — an empty set is refused
        // and falls back to keeping the first active company — so what was
        // asked for is not necessarily what is now active. Re-seed the draft
        // from the authoritative state instead of leaving it showing a
        // selection that was rejected.
        //
        // Nothing else does this reliably: `ACTIVE_COMPANIES_CHANGED` only
        // fires when the set actually changed, which is exactly NOT the case
        // when the request was refused, and the dropdown-close reset is a
        // desktop-only path — the mobile switcher renders inline and never
        // closes a dropdown, so it was left displaying every company unchecked
        // while company 1 was still the active one.
        this.reset();
        const state = {};
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
        const allowedCompanyIds = companyIds.filter((id) => isCompanyAllowed(id));
        const anySelected = allowedCompanyIds.some((id) =>
            this.selectedCompaniesIds.includes(id),
        );

        if (anySelected) {
            for (const companyId of allowedCompanyIds) {
                if (this.selectedCompaniesIds.includes(companyId)) {
                    this._deselectCompany(companyId);
                }
            }
        } else {
            for (const companyId of allowedCompanyIds) {
                this._selectCompany(companyId);
            }
        }
    }

    _selectCompany(companyId, unshift = false) {
        if (isCompanyAllowed(companyId)) {
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
                continue;
            }

            while (getActiveCompany(company.parent_id)) {
                company = getActiveCompany(company.parent_id);
            }

            if (rootCompany === undefined) {
                rootCompany = company;
            } else if (rootCompany !== company) {
                return false;
            }
        }

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
