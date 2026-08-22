/** @odoo-module native */
import { useSetupAction } from "@web/core/action_hook";
import { SearchModel } from "@web/search/search_model";
import { browser } from "@web/core/browser/browser";
import { router } from "@web/core/browser/router";
import { Domain } from "@web/core/domain";
import { useService } from "@web/core/utils/hooks";
import { toFolderValueId } from "@documents/views/utils";

export class DocumentsSearchModel extends SearchModel {
    setup(services) {
        super.setup(services);
        this.documentService = useService("document.document");
        this.orm = useService("orm");
        this.skipLoadClosePreview = false;
        useSetupAction({
            beforeLeave: () => {
                // The key `load()` reads back. Nothing in this module writes it,
                // so this only matters for an externally supplied link
                // (`/odoo/documents?user_folder_id=...`), which `load()` honours.
                this._updateRouteState({ user_folder_id: undefined });
            },
        });
    }

    /**
     * The folder category section, resolved by field name.
     *
     * The one way this file reaches that section: a positional `getSections()[0]`
     * or a hardcoded `sections.get(1)` stops being the folder section as soon as
     * the searchpanel arch gains a section or hides one.
     *
     * @returns {Object|undefined}
     */
    get folderCategory() {
        return this.categories.find((cat) => cat.fieldName === "user_folder_id");
    }

    async load(config) {
        if (this.documentService.initData.documentId || config.context.documents_init_document_id) {
            // Make sure target document is found (if accessible).
            config.irFilters.forEach((fil) => {
                fil.is_default = false;
            });
            for (const key in config.context) {
                // logic used in takeSearchDefaultsFromGlobalContext, here to group with above
                const searchDefaultMatch = /^search_default_(.*)$/.exec(key);
                if (searchDefaultMatch) {
                    delete config.context[key];
                }
                if (key === "documents_init_document_id") {
                    this.documentService.documentIdToRestoreOnce =
                        config.context.documents_init_document_id;
                    delete config.context[key];
                }
            }
        }

        await super.load(config);

        let folderId = router.current.user_folder_id || this.getSelectedFolderId();

        if (folderId) {
            if (!this.getFolderById(folderId)) {
                folderId = false;
            }
            this.toggleCategoryValue(this.folderCategory.id, folderId);
        }
    }

    /**
     * Override to add rootId
     *
     * @override
     */
    _createCategoryTree(sectionId) {
        const category = this.sections.get(sectionId);
        // No need to evict the numeric (real folder) keys first to 'forget'
        // archived folders: the base builder replaces `category.values` with a new
        // Map on every call, preserving only the synthetic `false` ("All") root.
        super._createCategoryTree(...arguments);
        const findRootId = (folder) => {
            if (!folder.parentId) {
                return folder.id;
            }
            const parent = category.values.get(folder.parentId);
            if (!parent) {
                return false;
            }
            if (parent.rootId !== undefined) {
                return parent.rootId;
            } else {
                const rootId = findRootId(parent);
                parent.rootId = rootId;
                return rootId;
            }
        };
        for (const [, folder] of category.values) {
            if (!folder.rootId) {
                folder.rootId = findRootId(folder);
            }
        }
    }

    /**
     * @override
     */
    takeSearchDefaultsFromGlobalContext() {
        const { searchDefaults, searchPanelDefaults } =
            super.takeSearchDefaultsFromGlobalContext(...arguments);
        if (searchPanelDefaults.user_folder_id) {
            // The panel keys real folders by number, the virtual roots by string.
            searchPanelDefaults.user_folder_id = toFolderValueId(
                searchPanelDefaults.user_folder_id
            );
            if (!this.globalContext.no_documents_unique_folder_id) {
                this.globalContext["documents_unique_folder_id"] =
                    searchPanelDefaults.user_folder_id;
            }
        }
        return { searchDefaults, searchPanelDefaults };
    }

    //---------------------------------------------------------------------
    // Actions / Getters
    //---------------------------------------------------------------------

    /**
     * Returns a description of each folder (record of documents.document, type === 'folder').
     * @returns {Object[]}
     */
    getFolders() {
        return [...(this.folderCategory?.values.values() ?? [])];
    }

    /**
     * Returns the folder corresponding to the provided id, if any, false otherwise.
     * @returns {Object | false}
     */
    getFolderById(folderId) {
        return this.folderCategory?.values.get(folderId) || false;
    }

    /**
     * Returns the id of the current selected folder, if any, false
     * otherwise.
     * @returns {number | string | false}
     */
    getSelectedFolderId() {
        return this.folderCategory?.activeValueId ?? false;
    }

    /**
     * Returns the current selected folder, if any, false otherwise.
     * @returns {Object | false}
     */
    getSelectedFolder() {
        return this.getFolderById(this.getSelectedFolderId());
    }

    /**
     * Returns the folder and all its parents, if any.
     * @returns {Object[]}
     */
    getFolderAndParents(folder) {
        const folders = [];
        while (folder) {
            folders.push(folder);
            folder = this.getFolderById(folder.folder_id || folder.user_folder_id);
        }
        return folders;
    }

    /**
     * Returns the current selected folder and all its parents, if any.
     * @returns {Object[]}
     */
    getSelectedFolderAndParents() {
        return this.getFolderAndParents(this.getFolderById(this.getSelectedFolderId() || false));
    }

    /**
     * Overridden to write the new value in the local storage.
     * And to write the folder_id in the url.
     * @override
     */
    toggleCategoryValue(sectionId, valueId) {
        super.toggleCategoryValue(...arguments);

        const selectedFolder = this.getSelectedFolder();
        if (!this.context.documents_view_secondary) {
            browser.localStorage.setItem("searchpanel_documents_document", valueId);
            this.documentService.updateDocumentURL(selectedFolder);
        }
        if (typeof valueId === "number") {
            if (selectedFolder.childrenIds && selectedFolder.childrenIds.length) {
                this.documentService.logAccess(selectedFolder.access_token);
            } else {
                this.documentService.logAccess(selectedFolder.access_token).then((result) => {
                    if (result && result?.reload) {
                        this._reloadSearchModel(true);
                    }
                });
            }
        }
    }

    //---------------------------------------------------------------------
    // Private
    //---------------------------------------------------------------------

    async _reloadSearchModel(reloadCategories) {
        // By default, categories are not reloaded.
        if (reloadCategories) {
            await this._reloadSearchPanel(true);
        }
        await this._notify();
    }

    async _reloadSearchPanel(skipUpdate = false) {
        await this._fetchSections(
            this.getSections((s) => s.type === "category"),
            []
        );
        if (!skipUpdate) {
            this.trigger("update-search-panel");
        }
    }

    /**
     * Optimize searches
     * @override
     */
    _getCategoryDomain() {
        const userFolderCategory = this.folderCategory;
        if (["COMPANY", "MY", "RECENT"].includes(userFolderCategory.activeValueId)) {
            return [["user_folder_id", "=", userFolderCategory.activeValueId]];
        }
        if (userFolderCategory.activeValueId === "TRASH") {
            return [["active", "=", false]];
        }
        if (userFolderCategory.activeValueId === "SHARED") {
            return Domain.and([
                [["shortcut_document_id", "=", false]], // no need to show them, the target will be here (or nested)
                [["user_folder_id", "=", "SHARED"]],
            ]).toList();
        }
        if (!userFolderCategory.activeValueId) {
            if (this.context.documents_unique_folder_id) {
                return [["id", "child_of", this.context.documents_unique_folder_id]];
            }
            return [];
        }
        const folder = this.getSelectedFolder();
        const folderIdToOpen = folder?.shortcut_document_id?.length
            ? folder.shortcut_document_id[0]
            : userFolderCategory.activeValueId;
        const result = super._getCategoryDomain();
        const folderLeafIdx = result.findIndex(
            (leaf) => leaf[0] === "user_folder_id" && leaf[1] === "="
        );
        if (folderLeafIdx !== -1) {
            result.splice(folderLeafIdx, 1, ...[["folder_id", "=", folderIdToOpen]]);
        }
        return result;
    }

    /**
     * @override Force specific ordering in RECENT and TRASH
     * and fall back to create_date desc as default otherwise.
     */
    get orderBy() {
        const activeFolderId = this.folderCategory?.activeValueId;
        if (activeFolderId === "TRASH") {
            return [
                { name: "create_date", asc: false },
                { name: "is_folder", asc: false },
            ];
        }
        if (activeFolderId === "RECENT") {
            return [
                { name: "is_folder", asc: true },
                { name: "last_access_date_group", asc: false },
                { name: "write_date", asc: false },
            ];
        }
        // Never mutate what `super.orderBy` hands back: it memoizes the array in
        // `this._orderBy` (which, with no favorite ordering, IS `globalOrderBy`)
        // and freezes it in debug mode. Pushing the default onto it threw
        // "Cannot add property 0, object is not extensible" and the documents
        // kanban failed to mount under `?debug=1`.
        const orderBy = super.orderBy;
        if (!orderBy.length) {
            // super.orderBy is the base search model's memoized getter —
            // frozen in dev mode ("consumers only read or rebuild it"), so
            // mutating it in place with push() throws
            // "Cannot add property 0, object is not extensible". Build a
            // fresh array instead.
            return [{ name: "create_date", asc: false }];
        }
        return orderBy;
    }

    get groupBy() {
        const groupBy = super.groupBy;
        if (!groupBy?.length && this.folderCategory?.activeValueId === "RECENT") {
            return ["last_access_date_group"];
        }
        return groupBy;
    }

    /**
     * Whether `valueId` is reachable by walking down from the category roots.
     *
     * Neither an unresolvable id nor a cycle is reachable today -- the arch parser
     * seeds `values[false]`, `search_panel_fetch` builds `rootIds`/`childrenIds`
     * out of `values`, and the ORM rejects a folder cycle outright. The `seen` set
     * is kept anyway: those invariants live in `web`, nothing enforces them from
     * here, and the cost of getting them wrong is a hung browser tab.
     *
     * @param {Object} category
     * @param {number|string|false} valueId
     * @returns {boolean}
     */
    _isCategoryValueReachable(category, valueId) {
        const queue = [...category.rootIds];
        const seen = new Set();
        while (queue.length) {
            const folderId = queue.pop();
            if (seen.has(folderId)) {
                continue;
            }
            seen.add(folderId);
            const folder = category.values.get(folderId);
            if (!folder) {
                continue;
            }
            if (folder.id === valueId) {
                return true;
            }
            queue.push(...folder.childrenIds);
        }
        return false;
    }

    /**
     * @override
     */
    _ensureCategoryValue(category, valueIds) {
        if (
            valueIds.includes(category.activeValueId) &&
            this._isCategoryValueReachable(category, category.activeValueId)
        ) {
            return;
        }
        if (this.context.documents_init_folder_id !== undefined) {
            category.activeValueId = this.context.documents_init_folder_id || false;
            return;
        }
        // If not set in context, or set to an unknown value, set active value
        // from localStorage
        const storageItem = browser.localStorage.getItem("searchpanel_documents_document");
        if (storageItem && !["COMPANY", "MY", "RECENT", "SHARED", "TRASH"].includes(storageItem)) {
            try {
                // Usually a folder id serialized as JSON, but a bad URL param can
                // have been persisted verbatim, and an unguarded parse would throw
                // on every load until localStorage is cleared.
                category.activeValueId = JSON.parse(storageItem);
            } catch {
                category.activeValueId = false;
            }
        } else {
            category.activeValueId = storageItem;
        }
        if (
            ["COMPANY", "MY", "RECENT", "SHARED", "TRASH"].includes(category.activeValueId) ||
            (valueIds.includes(category.activeValueId) &&
                this._isCategoryValueReachable(category, category.activeValueId))
        ) {
            return;
        }
        // valueIds might contain different values than category.values
        if (category.values.has(category.activeValueId)) {
            // We might be in a deleted subfolder, try to find the parent.
            let newSection = category.values.get(
                category.values.get(category.activeValueId).parentId
            );
            while (newSection && !this._isCategoryValueReachable(category, newSection.id)) {
                newSection = category.values.get(newSection.parentId);
            }
            if (newSection) {
                category.activeValueId = newSection.id || valueIds[Number(valueIds.length > 1)];
            } else {
                category.activeValueId = this.documentService.userIsInternal
                    ? "COMPANY"
                    : valueIds[0];
            }
            browser.localStorage.setItem("searchpanel_documents_document", category.activeValueId);
        } else {
            // If still not a valid value, default to All (id=false)
            category.activeValueId = false;
        }
    }

    /**
     * @override
     */
    _shouldWaitForData() {
        return true;
    }

    _updateRouteState(state) {
        router.pushState(state);
    }
}
