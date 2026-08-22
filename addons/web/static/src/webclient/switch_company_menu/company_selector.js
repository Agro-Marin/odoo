// @ts-check
/** @odoo-module native */

import { router } from "@web/core/browser/router";
import { user } from "@web/core/user";
import { symmetricalDifference } from "@web/core/utils/collections/arrays";

/**
 * @type {WeakMap<object[], Map<number, any>>}
 */
const indexByCompanies = new WeakMap();

/**
 * @param {number} cid
 * @returns {Object | undefined}
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
 * @type {WeakMap<object[], Set<number>>}
 */
const allowedIdsByCompanies = new WeakMap();

/**
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
            } catch (error) {
                console.warn(
                    "Could not check read access for the new company selection",
                    error,
                );
            }
        }

        user.activateCompanies(newCompanyIds, {
            includeChildCompanies: false,
            reload: false,
        });
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
     * @param {number} companyId
     * @returns {number[]}
     */
    _getBranches(companyId) {
        return getCompany(companyId)?.child_ids ?? [];
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
