/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { useService } from "@web/core/utils/hooks";
import { SearchModel } from "@web/search/search_model";

const log = makeLogger("website.view.page_search_model");

export class PageSearchModel extends SearchModel {
    /**
     * @override
     */
    setup() {
        super.setup(...arguments);
        this.website = useService("website");
    }

    /**
     * @override
     */
    async load() {
        await super.load(...arguments);

        const endFetch = log.perf("load fetchWebsites");
        await this.website.fetchWebsites();
        endFetch();

        log.logic("load website filters", () => ({
            resModel: this.resModel,
            hasWebsiteField: Boolean(this.searchViewFields.website_id),
        }));
        if (this.searchViewFields.website_id) {
            await this.createFilterForAllWebsites();
            await this.selectCurrentWebsiteFilter();
        }
    }

    async createFilterForAllWebsites() {
        const existingWebsiteFilters = this.getSearchItems(
            (searchItem) =>
                searchItem.type === "filter" && searchItem.name.startsWith("website_"),
        );

        if (existingWebsiteFilters.length === this.website.websites.length) {
            log.logic("createFilterForAllWebsites skip: filters exist", () => ({
                filters: existingWebsiteFilters.length,
            }));
            return;
        }

        const websiteFilters = await this.fetchWebsiteFilters();
        log.pipeline("createFilterForAllWebsites", () => ({
            filters: websiteFilters.length,
        }));
        this._createGroupOfSearchItems(websiteFilters);
    }

    async fetchWebsiteFilters() {
        let websitePageIds = {};
        if (this.resModel === "website.page") {
            const websiteIds = this.website.websites.map((website) => website.id);
            const endPageIds = log.perf("get_website_page_ids", { websiteIds });
            websitePageIds = await this.orm.call("website", "get_website_page_ids", [
                websiteIds,
            ]);
            endPageIds();
        }

        return this.website.websites.map((website) => {
            const websiteDomain =
                this.resModel === "website.page"
                    ? [["id", "in", websitePageIds[website.id] || []]]
                    : [["website_id", "in", [false, website.id]]];

            return {
                name: `website_${website.id}`,
                description: website.name,
                domain: websiteDomain,
                type: "filter",
            };
        });
    }

    async selectCurrentWebsiteFilter() {
        const currentlySelectedWebsiteFilters = this.getSearchItems(
            (searchItem) =>
                searchItem.type === "filter" &&
                searchItem.name.startsWith("website_") &&
                searchItem.isActive,
        );
        if (currentlySelectedWebsiteFilters.length) {
            log.logic("selectCurrentWebsiteFilter skip: already selected");
            return;
        }

        const currentWebsite = await this.getCurrentWebsite();
        const [currentWebsiteFilter] = this.getSearchItems(
            (searchItem) =>
                searchItem.type === "filter" &&
                searchItem.name === `website_${currentWebsite.id}`,
        );
        if (currentWebsiteFilter) {
            log.logic("selectCurrentWebsiteFilter toggle", () => ({
                websiteId: currentWebsite.id,
            }));
            this.toggleSearchItem(currentWebsiteFilter.id);
        }
    }

    /**
     * @returns {Object}
     */
    async getCurrentWebsite() {
        const endCurrent = log.perf("get_current_website");
        const currentWebsite = await this.orm.call("website", "get_current_website");
        endCurrent({ currentWebsite });
        if (currentWebsite) {
            return this.website.websites.find((w) => w.id === currentWebsite[0]);
        }
        return this.website.websites[0];
    }

    async refreshFilterForAllWebsites() {
        const websiteFilters = await this.fetchWebsiteFilters();
        log.pipeline("refreshFilterForAllWebsites", () => ({
            filters: websiteFilters.length,
        }));

        for (const websiteFilter of websiteFilters) {
            Object.values(this.searchItems).forEach((searchItem) => {
                if (
                    searchItem.type === "filter" &&
                    searchItem.name === websiteFilter.name
                ) {
                    searchItem.domain = websiteFilter.domain;
                }
            });
        }

        await this._notify();
    }
}
