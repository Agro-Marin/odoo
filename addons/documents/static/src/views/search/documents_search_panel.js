/** @odoo-module native */
import { AccessRightsUpdateConfirmationDialog } from "@documents/owl/components/access_update_confirmation_dialog/access_update_confirmation_dialog";
import { _t } from "@web/core/translation";
import { browser } from "@web/core/browser/browser";
import { SearchPanel } from "@web/search/search_panel/search_panel";
import { useNestedSortable } from "@web/core/utils/dnd";
import { usePopover } from "@web/ui/popover";
import { useBus, useService } from "@web/core/utils/hooks";
import { utils as uiUtils } from "@web/ui/viewport";
import { toFolderValueId } from "@documents/views/utils";
import { Component, onWillStart, useState } from "@odoo/owl";

const DND_ALLOWED_SPECIAL_DESTINATIONS = ["COMPANY", "MY"];
const LONG_TOUCH_THRESHOLD = 400;

/**
 * This file defines the DocumentsSearchPanel component, an extension of the
 * SearchPanel to be used in the documents kanban/list views.
 */

export class DocumentsSearchPanelItemSettingsPopover extends Component {
    static template = "documents.DocumentsSearchPanelItemSettingsPopover";
    static props = [
        "close", // Function, close the popover
        "createChildEnabled", // Whether we have the option to create a new child or not
        "onCreateChild", // Function, create new child
        "onEdit", // Function, edit element
        "isShareable", // Whether we have the option to share
        "onShare", // Function, share folder
        "isEditable",
    ];
}

export class DocumentsSearchPanel extends SearchPanel {
    static modelExtension = "DocumentsSearchPanel";
    // Getters, not fields. Owl reads `C.template` when it builds each component
    // node, and a template read `constructor.subTemplates` on every render, so a
    // getter is asked the question again every time it is asked. As assignments
    // these ran once, when the bundle was evaluated: the panel was fixed to
    // whatever the viewport happened to be at import time and stayed there for
    // the session, so a window narrowed after load kept the desktop panel and a
    // bundle evaluated before layout settled could pick the wrong one outright.
    static get template() {
        return !uiUtils.isSmall()
            ? "documents.SearchPanel"
            : "documents.SearchPanel.Small";
    }
    static get subTemplates() {
        return !uiUtils.isSmall()
            ? {
                  section: "web.SearchPanel.Section",
                  category: "documents.SearchPanel.Category",
                  filtersGroup: "documents.SearchPanel.FiltersGroup",
              }
            : {
                  section: "web.SearchPanel.Section",
                  category: "documents.SearchPanel.Category.Small",
                  filtersGroup: "documents.SearchPanel.FiltersGroup.Small",
              };
    }
    static rootIcons = {
        false: "fa-regular fa-folder",
        COMPANY: "fa-solid fa-building",
        MY: "fa-solid fa-hard-drive",
        RECENT: "fa-regular fa-clock",
        SHARED: "fa-solid fa-users",
        TRASH: "fa-solid fa-trash",
    };
    setup() {
        super.setup(...arguments);
        const { uploads } = useService("file_upload");
        this.documentService = useService("document.document");
        // `useState`, not the service's own reactive: reading the latter during
        // render subscribes nobody, so the spinner would never appear or clear on
        // its own.
        this.documentUploads = useState(uploads);
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.action = useService("action");
        this.popover = usePopover(DocumentsSearchPanelItemSettingsPopover, {
            onClose: () => this.onPopoverClose?.(),
            class: "o_search_panel_item_settings_popover",
        });
        this.dialog = useService("dialog");

        onWillStart(async () => {
            // onWillStart callbacks run concurrently, and the base panel fills
            // `state.expanded` in its own, so wait for the sections first.
            await this.env.searchModel.sectionsPromise;
            if (this.env.model.config.context.active_model) {
                // Ensure folders in search panel are folded when users come from another app
                const categories = await this.env.searchModel.getSections(
                    (s) => s.type === "category",
                );
                for (const category of categories) {
                    this.state.expanded[category.id] = {};
                }
            } else {
                const selectedFolderId =
                    await this.env.searchModel.getSelectedFolderId();
                if (selectedFolderId) {
                    this.state.expanded[this.sections[0].id]["COMPANY"] = true;
                    this._expandFolder({ folderId: selectedFolderId });
                }
            }
        });

        useBus(this.env.documentsView.bus, "documents-expand-folder", (ev) => {
            this._expandFolder(ev.detail);
        });

        useBus(this.env.searchModel, "update-search-panel", async () => {
            this.updateActiveValues();
            this.render();
        });

        useNestedSortable({
            ref: this.root,
            groups: ".o_search_panel_category",
            elements: "li:not(.o_all_or_trash_category)",
            enable: () => this.documentService.userIsInternal,
            nest: true,
            nestInterval: 10,
            /**
             * When the placeholder moves, unfold the new parent and show/hide carets
             * where needed.
             * @param {HTMLElement} parent - parent element of where the element was moved
             * @param {HTMLElement} newGroup - group in which the element was moved
             * @param {{parent: HTMLElement}} prevPos - element's parent before the move
             * @param {HTMLElement} placeholder - hint element showing the current position
             */
            onMove: ({ parent, newGroup, prevPos, placeholder }) => {
                if (parent) {
                    parent.classList.add("o_has_treeEntry");
                    placeholder.classList.add("o_treeEntry");
                    const parentSectionId = parseInt(newGroup.dataset.sectionId);
                    const parentValueId = parseInt(parent.dataset.valueId);
                    this.state.expanded[parentSectionId][parentValueId] = true;
                } else {
                    placeholder.classList.remove("o_treeEntry");
                }
                if (prevPos.parent && !prevPos.parent.querySelector("li")) {
                    prevPos.parent.classList.remove("o_has_treeEntry");
                }
            },
            onDrop: async ({ element, parent, next }) => {
                const draggingFolderId = parseInt(element.dataset.valueId);
                const draggingFolder =
                    this.env.searchModel.getFolderById(draggingFolderId);
                const draggingFolderRootId = draggingFolder.rootId;
                let parentFolderId = parent ? parent.dataset.valueId : false;
                const beforeFolderId = next ? parseInt(next.dataset.valueId) : false;
                if (
                    draggingFolderId === parseInt(parentFolderId) ||
                    isNaN(draggingFolderId) ||
                    !parentFolderId ||
                    this._notifyWrongDropDestination(parentFolderId)
                ) {
                    return;
                }
                // Real folders are keyed by numeric id, the special destinations
                // ("MY", "COMPANY", ...) by string.
                const parentFolderRootId = this.env.searchModel.getFolderById(
                    toFolderValueId(parentFolderId),
                ).rootId;
                if (
                    !this.documentService.userIsDocumentManager &&
                    (!parentFolderRootId || parentFolderRootId === "COMPANY")
                ) {
                    return;
                }
                if (parentFolderRootId === "MY" && draggingFolderRootId !== "MY") {
                    await this.orm.call(
                        "documents.document",
                        "action_create_shortcut",
                        [draggingFolderId],
                        { location_user_folder_id: parentFolderId.toString() },
                    );
                    return this.env.searchModel._reloadSearchModel(true);
                }
                if (!DND_ALLOWED_SPECIAL_DESTINATIONS.includes(parentFolderId)) {
                    parentFolderId = parseInt(parentFolderId);
                }
                const parentFolder = this.env.searchModel.getFolderById(parentFolderId);
                if (
                    !DND_ALLOWED_SPECIAL_DESTINATIONS.includes(parentFolderId) &&
                    (draggingFolder.access_internal !== parentFolder.access_internal ||
                        draggingFolder.access_via_link !==
                            parentFolder.access_via_link ||
                        (parentFolder.access_via_link !== "none" &&
                            draggingFolder.is_access_via_link_hidden !==
                                parentFolder.is_access_via_link_hidden))
                ) {
                    this.dialog.add(AccessRightsUpdateConfirmationDialog, {
                        destinationFolder: parentFolder,
                        confirm: async () => {
                            await this.orm.call(
                                "documents.document",
                                "action_move_folder",
                                [
                                    [draggingFolderId],
                                    parentFolderId.toString() || false,
                                    beforeFolderId,
                                ],
                            );
                            await this.env.searchModel._reloadSearchModel(true);
                        },
                        cancel: () => {},
                    });
                    return;
                }
                await this.orm.call("documents.document", "action_move_folder", [
                    [draggingFolderId],
                    parentFolderId ? parentFolderId.toString() : false,
                    beforeFolderId,
                ]);
                await this.env.searchModel._reloadSearchModel(true);
            },
        });
    }

    /**
     * Whether an upload is currently landing in `folderId`.
     *
     * Read off `upload.targetFolderId`, which `DocumentService.uploadDocument`
     * stamps on the upload: the form data cannot carry it, since
     * `/documents/upload` declares its parameters explicitly and takes
     * `user_folder_id` only for the two drive roots.
     *
     * @param {number|String} folderId
     * @returns {boolean}
     */
    isUploadingInFolder(folderId) {
        return Object.values(this.documentUploads).some(
            (upload) => upload.targetFolderId === folderId,
        );
    }

    //---------------------------------------------------------------------
    // Selection
    //---------------------------------------------------------------------

    /**
     * @param {Object} category
     * @param {Object} value
     */
    async toggleCategory(category, value) {
        if (category.activeValueId !== value.id) {
            const folder = this.env.searchModel.getFolderById(value.id);
            const isShortcut = !!folder.shortcut_document_id?.length;
            if (
                isShortcut &&
                !this.env.searchModel.getFolderById(folder.shortcut_document_id[0])
            ) {
                // Unknown folders are in the Trash.
                return this.env.searchModel.toggleCategoryValue(category.id, "TRASH");
            }
            this.env.searchModel.toggleCategoryValue(category.id, value.id);
        }
    }

    /**
     * @param {*} category
     * @param {*} value
     */
    async toggleFold(category, value) {
        if (value.childrenIds.length) {
            const categoryState = this.state.expanded[category.id];
            categoryState[value.id] = !categoryState[value.id];
        } else {
            this.getDropdownState(category.id).close();
        }
    }

    //---------------------------------------------------------------------
    // Edition
    //---------------------------------------------------------------------

    // Support for edition on mobile
    resetLongTouchTimer() {
        if (this.longTouchTimer) {
            browser.clearTimeout(this.longTouchTimer);
            this.longTouchTimer = null;
        }
    }

    onSectionValueTouchStart(ev, section, value) {
        if (!uiUtils.isSmall() || typeof value !== "number") {
            return;
        }
        this.touchStartMs = Date.now();
        if (!this.longTouchTimer) {
            this.longTouchTimer = browser.setTimeout(() => {
                // `openEditPopover` is not implemented -- the item-settings
                // popover it would open is currently unreachable.
                this.openEditPopover?.(ev, section, value);
                this.resetLongTouchTimer();
            }, LONG_TOUCH_THRESHOLD);
        }
    }

    onSectionValueTouchEnd() {
        const elapsedTime = Date.now() - this.touchStartMs;
        if (elapsedTime < LONG_TOUCH_THRESHOLD) {
            this.resetLongTouchTimer();
        }
    }

    onSectionValueTouchMove() {
        this.resetLongTouchTimer();
    }

    /**
     * Unfold `folderId` and its ancestors.
     *
     * @param {Object} param0
     * @param {number|String} param0.folderId
     */
    _expandFolder({ folderId }) {
        let needRefresh = false;
        const sectionId = this.sections[0].id;
        const folders = this.env.searchModel.getFolderAndParents(
            this.env.searchModel.getFolderById(folderId),
        );
        if (!folders.length) {
            // The panel does not hold this folder, so there is no chain to
            // unfold. `getFolderById` answers `false` for an id it does not know
            // and `getFolderAndParents(false)` is `[]`, which the ancestor test
            // below dereferences. `jumpToTarget` reaches here with the target's
            // `user_folder_id` without first reloading the panel, so a shortcut
            // to a folder the user cannot see gets here.
            return;
        }
        if (
            folders[0].id === "COMPANY" ||
            this.state.expanded[sectionId][folders[0].rootId]
        ) {
            for (const folder of folders) {
                if (!this.state.expanded[sectionId][folder.id]) {
                    this.state.expanded[sectionId][folder.id] = true;
                    needRefresh = true;
                }
            }
        }
        if (needRefresh) {
            this.render(true);
        }
    }

    _notifyWrongDropDestination(folderId) {
        if (isNaN(folderId) && !DND_ALLOWED_SPECIAL_DESTINATIONS.includes(folderId)) {
            this.notification.add(
                _t(
                    "You can't create shortcuts in or move documents to this special folder.",
                ),
                {
                    title: _t("Invalid operation"),
                    type: "warning",
                },
            );
            return true;
        }
    }
}
