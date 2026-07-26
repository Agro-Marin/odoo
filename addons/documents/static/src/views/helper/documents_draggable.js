/** @odoo-module native */
import { markup } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { DRAGGED_CLASS } from "@web/core/utils/dnd/draggable_hook_builder";
import { makeDraggableHook } from "@web/core/utils/dnd/draggable_hook_builder_owl";
import { createDocumentFragmentFromContent } from "@web/core/utils/dom/html";
import { closestScrollableX, closestScrollableY } from "@web/core/utils/dom/scrolling";

/**
 * Why `targetFolder` cannot receive a drag of `draggedRecords`, or "" when it
 * can.
 *
 * Pure and exported so both consumers below share one answer and so the rules
 * are testable without a drag, a DOM or a component. They used to be inlined in
 * the hover handler while `onDrop` re-derived a shorter list of its own, which
 * let the two disagree about the same target.
 *
 * @param {Object} params
 * @param {{movableRecordIds: number[], nonMovableRecordIds: number[]}} params.draggedRecords
 * @param {Object|false} params.targetFolder
 * @param {boolean} params.userIsDocumentManager
 * @param {(folder: Object) => Object[]} params.getFolderAndParents
 * @returns {String} translated reason, empty when the drop is allowed
 */
export function dropRejectionReason({
    draggedRecords,
    targetFolder,
    userIsDocumentManager,
    getFolderAndParents,
}) {
    if (!targetFolder || ["RECENT", "SHARED"].includes(targetFolder.id)) {
        return _t("You can't create shortcuts in nor move documents to this special folder.");
    }
    if (draggedRecords.nonMovableRecordIds.length && targetFolder.id === "TRASH") {
        return _t("There is at least one document you cannot move to trash in your selection.");
    }
    // Write permission is checked for real folders too, not only for COMPANY.
    // `user_permission` is served for every search-panel folder, and
    // `documents.document.write` raises AccessError ("You can't access that
    // folder_id.") when the destination is not `edit` -- so dragging into a
    // read-only folder used to show a perfectly normal drop badge and only fail
    // afterwards, with a server error dialog.
    const canWrite =
        targetFolder.id === "COMPANY"
            ? targetFolder.user_permission === "edit" || userIsDocumentManager
            : typeof targetFolder.id !== "number" || targetFolder.user_permission === "edit";
    if (!canWrite) {
        return _t("You don't have the rights to write in this folder.");
    }
    // Hoisted out of the `some()`: the ancestor chain is a property of the
    // target, not of the dragged record, and was rebuilt once per dragged
    // document.
    const ancestorIds = getFolderAndParents(targetFolder).map((folder) => folder.id);
    if (draggedRecords.movableRecordIds.some((id) => ancestorIds.includes(id))) {
        return _t("You cannot move a folder into itself or a children.");
    }
    return "";
}

export const useDraggableDocuments = makeDraggableHook({
    name: "useDraggableDocuments",
    acceptedParams: {
        model: [Object],
        targetSelector: [String],
    },

    onComputeParams({ ctx, params }) {
        ctx.model = params.model;
        ctx.targetSelector = params.targetSelector;
        ctx.edgeScrolling.force = true;
        ctx.followCursor = false;
    },

    // NB: per-drag state lives on `ctx` (one object per hook *instance*), never on
    // `this`: handlers are invoked as `hookParams[name]({...})`, so `this` is the
    // module-level hook definition, shared by every component using this hook.
    onWillStartDrag({ ctx }) {
        ctx.tempDraggedElements = [];
        ctx.initialPositions = [];
        ctx.selectedElements = [];
        ctx.draggedRecords = null;
        ctx.lastDragTime = 0;
        ctx.isInvalidTarget = false;
    },

    onDragStart({ ctx, callHandler, addClass, addCleanup, addStyle, addListener, removeClass }) {
        const { current, model, ref, targetSelector } = ctx;
        const { element } = current;
        addClass(ref.el, "o_documents_dragging");
        removeClass(element, DRAGGED_CLASS);
        const searchPanelEl = document.querySelector(".o_documents_search_panel");
        const currentElementId = parseInt(element.dataset.valueId);
        const currentRecord = model.root.records.find((r) => r.data.id === currentElementId);
        if (!currentRecord) {
            // The dragged record is not on the current page (paginated out / removed).
            return;
        }

        // Reinitialize the selection if drag action is on an unselected document
        if (
            !model.root.selection.length ||
            !model.root.selection.map((r) => r.data.id).includes(currentElementId)
        ) {
            model.root.selection.forEach((r) => (r.selected = false));
            currentRecord.selected = true;
        }
        this._setDraggedRecords(ctx, model);

        const recordData = currentRecord.data;
        current.dragMessageText = recordData.display_name;
        current.dragMessage = this._createDnDElement(recordData, model.root.selection.length);
        ref.el.append(current.dragMessage);

        const allElements = ref.el.classList.contains("o_kanban_renderer")
            ? ref.el.querySelectorAll(".o_kanban_record:not(.o_kanban_ghost)")
            : ref.el.querySelectorAll(".o_data_row");
        ctx.selectedElements = Array.from(allElements).filter((el) =>
            ctx.draggedRecords.all.includes(parseInt(el.dataset.valueId))
        );
        for (const selectedEl of ctx.selectedElements) {
            const sourceRect = selectedEl.getBoundingClientRect();
            const sourceName = model.root.records.find(
                (r) => r.data.id === parseInt(selectedEl.dataset.valueId)
            ).data.name;
            ctx.initialPositions.push({
                initialTop: sourceRect.top,
                initialLeft: sourceRect.left,
            });

            const tempEl = document.createElement("div");
            tempEl.innerText = sourceName;
            tempEl.classList.add("o_record_temporary");
            ctx.tempDraggedElements.push(tempEl);
            document.body.append(tempEl);
            addCleanup(() => tempEl.remove());

            tempEl.style.left = `${sourceRect.left}px`;
            tempEl.style.top = `${sourceRect.top}px`;

            addStyle(selectedEl, { opacity: 0.3 });
        }
        addStyle(current.dragMessage, { opacity: 1 });
        setTimeout(() => {
            ctx.tempDraggedElements.forEach((temp) => temp.remove());
            ctx.tempDraggedElements = [];
        }, 250);

        const switchContainer = (container) => {
            current.container = container;
            [current.scrollParentX, current.scrollParentY] = [
                closestScrollableX(container),
                closestScrollableY(container),
            ];
        };

        // Search Panel Event Handlers
        const onSearchPanelFolderPointerOver = (ev) => {
            const targetClasses = ev.target.classList;
            if (
                targetClasses.contains("o_search_panel_label") ||
                targetClasses.contains("o_search_panel_label_title") ||
                targetClasses.contains("w-100")
            ) {
                const valueEl = ev.target.closest(".o_search_panel_category_value");
                const targetFolder = model.env.searchModel.getFolderById(
                    parseInt(valueEl.dataset.valueId) || valueEl.dataset.valueId
                );
                this._checkTargetValidity(
                    ctx,
                    targetFolder,
                    model,
                    current.dragMessage,
                    current.dragMessageText,
                    true
                );
                if (!ev.ctrlKey) {
                    ref.el.classList.remove("o_documents_dnd_shortcut");
                }

                const allSelected = searchPanelEl.querySelectorAll(":scope .o_drag_over_selector");
                for (const selected of allSelected) {
                    selected.classList.remove("o_drag_over_selector");
                }
                addClass(valueEl, "o_drag_over_selector");
                if (!ctx.isInvalidTarget) {
                    model.env.documentsView.bus.trigger("documents-expand-folder", {
                        folderId: targetFolder.id,
                    });
                }
            }
        };

        const onSearchPanelFolderPointerEnter = (ev) => {
            switchContainer(searchPanelEl);
        };

        const onSearchPanelFolderPointerLeave = (ev) => {
            switchContainer(ref.el);
            if (ctx.isInvalidTarget) {
                ctx.isInvalidTarget = false;
                this._resetDragMessage(current.dragMessage, current.dragMessageText);
            }
            const allSelected = searchPanelEl.querySelectorAll(":scope .o_drag_over_selector");
            for (const selected of allSelected) {
                selected.classList.remove("o_drag_over_selector");
            }
        };

        // Target Folders Event Handlers
        const onTargetFolderPointerEnter = (ev) => {
            const targetFolder = model.env.searchModel.getFolderById(
                parseInt(ev.currentTarget.dataset.valueId) || ev.currentTarget.dataset.valueId
            );
            this._checkTargetValidity(
                ctx,
                targetFolder,
                model,
                current.dragMessage,
                current.dragMessageText
            );

            callHandler("onTargetPointerEnter", {
                target: ev.currentTarget,
                isInvalid: ctx.isInvalidTarget,
            });
        };

        const onTargetFolderPointerLeave = (ev) => {
            if (ctx.isInvalidTarget) {
                ctx.isInvalidTarget = false;
                this._resetDragMessage(current.dragMessage, current.dragMessageText);
            }
            callHandler("onTargetPointerLeave", { target: ev.currentTarget });
        };

        for (const targetFolder of ref.el.querySelectorAll(targetSelector)) {
            addListener(targetFolder, "pointerenter", onTargetFolderPointerEnter);
            addListener(targetFolder, "pointerleave", onTargetFolderPointerLeave);
        }
        if (searchPanelEl) {
            addListener(searchPanelEl, "pointerover", onSearchPanelFolderPointerOver);
            addListener(searchPanelEl, "pointerenter", onSearchPanelFolderPointerEnter);
            addListener(searchPanelEl, "pointerleave", onSearchPanelFolderPointerLeave);
        }

        this._updateDragInfoPosition(ctx, addStyle);

        addCleanup(() => {
            current.dragMessage.remove();
        });
    },

    onDrag({ ctx, addStyle }) {
        this._updateDragInfoPosition(ctx, addStyle);
        if (ctx.tempDraggedElements?.length) {
            const now = Date.now();
            if (now - ctx.lastDragTime >= 50) {
                ctx.lastDragTime = now;
                this._updateTempElementsAnimation(ctx);
            }
        }
    },

    async onDrop({ ctx, target }) {
        const { model, ref } = ctx;

        if (!ctx.current.dragMessage) {
            // Drag was never properly initialized (see onDragStart early return),
            // so draggedRecords is stale/undefined — do not issue any move.
            return;
        }
        if (ctx.isInvalidTarget) {
            return;
        }
        const targetElement =
            target.closest(".o_search_panel_category_value") ||
            target.closest(".o_kanban_record") ||
            target.closest(".o_data_row");
        if (!targetElement) {
            return;
        }
        if (targetElement.dataset.valueId === "TRASH") {
            if (
                ctx.draggedRecords.movableRecordIds.length &&
                (await model.documentService.moveToTrash(ctx.draggedRecords.movableRecordIds))
            ) {
                model.env.services.notification.add(
                    _t(
                        "%s document(s) sent to trash.",
                        ctx.draggedRecords.movableRecordIds.length
                    ),
                    { type: "success" }
                );
            }
            await model.env.searchModel._reloadSearchModel(true);
            return;
        }
        const targetFolderId =
            parseInt(targetElement.dataset.valueId) || targetElement.dataset.valueId;
        const sourceFolder = model.env.searchModel.getSelectedFolder();
        const targetFolder = model.env.searchModel.getFolderById(targetFolderId);

        if (sourceFolder === targetFolder) {
            return;
        }

        // Target validity is only computed in the hover handlers, which fire on
        // folder elements. A drop can still land on a non-folder card/row
        // (getFolderById -> false), on a virtual folder that cannot receive
        // documents (RECENT/SHARED), on a folder the user cannot write to, or on
        // one of the dragged folders itself. Re-run the same predicate the hover
        // feedback uses rather than a second, shorter list that can drift from it.
        if (
            ["RECENT", "SHARED", "TRASH"].includes(targetFolder?.id) ||
            ctx.draggedRecords.all.includes(targetFolder?.id) ||
            this._dropRejectionReason(ctx, targetFolder, model)
        ) {
            return;
        }

        if (targetFolder.id === "COMPANY") {
            await model.documentService.moveToCompanyRoot(ctx.draggedRecords);
            model.env.searchModel._reloadSearchModel(true);
            return;
        }

        let expectedAccessRightsChanges = false;
        if (
            !isNaN(targetFolder.id) && // no change for these fields
            this._getMovableRecords(model).some(
                (record) =>
                    record.data.access_internal !== targetFolder.access_internal ||
                    record.data.access_via_link !== targetFolder.access_via_link ||
                    (targetFolder.access_via_link !== "none" &&
                        record.data.is_access_via_link_hidden !==
                            targetFolder.is_access_via_link_hidden)
            )
        ) {
            expectedAccessRightsChanges = true;
        }

        await model.documentService.moveOrCreateShortcut(
            ctx.draggedRecords,
            targetFolder,
            ref.el.classList.contains("o_documents_dnd_shortcut"),
            expectedAccessRightsChanges
        );

        // Awaited, in this order. `notify()` fired immediately after an
        // un-awaited `load()` renders the pre-move root, and nothing re-renders
        // when the load lands (`RelationalModel.load` does not notify) -- the
        // moved rows only disappeared because the search-panel reload below
        // happened to trigger a render of its own. This is the same sequence
        // `DocumentsModelMixin._notifyChange` uses.
        await model.load();
        await model.notify();
        await model.env.searchModel._reloadSearchModel(true);
    },

    _getMovableRecords(model) {
        return model.root.selection.filter(
            (record) => !record.data.lock_uid && record.data.user_permission === "edit"
        );
    },

    _setDraggedRecords(ctx, model) {
        const movableRecordIds = this._getMovableRecords(model).map((record) => record.data.id);
        const nonMovableRecordIds = model.root.selection
            .filter((record) => !movableRecordIds.includes(record.data.id))
            .map((record) => record.data.id);
        ctx.draggedRecords = {
            movableRecordIds,
            nonMovableRecordIds,
            all: [...movableRecordIds, ...nonMovableRecordIds],
        };
    },

    _createDnDElement(recordData, documentsCount) {
        const docCountPill =
            documentsCount > 1
                ? markup`<div class="o_documents_dnd_pill bg-success border border-light rounded-circle p-1 text-center">${documentsCount}</div>`
                : "";
        return createDocumentFragmentFromContent(markup`
            <span class="o_documents_dnd o_documents_dnd_info d-flex p-2">
                <i class="o_documents_mimetype_icon o_image" data-mimetype=${recordData.mimetype} title=${recordData.mimetype}></i>
                <span class="o_documents_dnd_text ps-2">${recordData.display_name}</span>
                <div class="o_documents_dnd_pill_container d-flex position-absolute top-0 start-100 translate-middle">
                    <div class="o_documents_dnd_pill o_documents_dnd_modifier bg-info border border-light rounded-circle p-1">
                        <i class="fa-solid fa-square-up-right"></i>
                    </div>
                    ${docCountPill}
                </div>
            </span>
        `).body.firstChild;
    },

    /**
     * Adapter from the hook's `ctx`/`model` onto {@link dropRejectionReason}.
     * @returns {String}
     */
    _dropRejectionReason(ctx, targetFolder, model) {
        return dropRejectionReason({
            draggedRecords: ctx.draggedRecords,
            targetFolder,
            userIsDocumentManager: model.documentService.userIsDocumentManager,
            getFolderAndParents: (folder) => model.env.searchModel.getFolderAndParents(folder),
        });
    },

    _checkTargetValidity(ctx, targetFolder, model, dragMessage, dragMessageText, reset = false) {
        const errorMessage = this._dropRejectionReason(ctx, targetFolder, model);
        ctx.isInvalidTarget = Boolean(errorMessage);
        if (errorMessage) {
            this._setErrorMessage(dragMessage, errorMessage);
        } else if (reset) {
            this._resetDragMessage(dragMessage, dragMessageText);
        }
    },

    _setErrorMessage(dragMessage, errorMessage) {
        dragMessage.classList.remove("o_documents_dnd_info");
        dragMessage.classList.add("alert", "alert-warning");
        dragMessage.querySelector(".o_documents_dnd_text").textContent = errorMessage;
    },

    _resetDragMessage(dragMessage, dragMessageText) {
        dragMessage.classList.remove("alert", "alert-warning");
        dragMessage.classList.add("o_documents_dnd_info");
        dragMessage.querySelector(".o_documents_dnd_text").textContent = dragMessageText;
    },

    _updateDragInfoPosition(ctx, addStyle) {
        const { dragMessage } = ctx.current;
        if (!dragMessage) {
            // onDragStart bailed out (record paginated out / removed) without
            // building a drag badge; nothing to position.
            return;
        }
        addStyle(dragMessage, {
            left: `${ctx.pointer.x}px`,
            top: `${ctx.pointer.y}px`,
        });
    },

    _updateTempElementsAnimation(ctx) {
        const { dragMessage } = ctx.current;
        if (!dragMessage) {
            return;
        }
        // Measure once, outside the loop. `dragMessage` is the same element on
        // every iteration, but reading its rect *after* having written
        // `clone.style` in the previous one forced a synchronous layout per
        // dragged document -- i.e. N reflows every animation tick, on the
        // drag path, which is exactly where a multi-selection drag got slow.
        const { width, height } = dragMessage.getBoundingClientRect();
        ctx.tempDraggedElements.forEach((clone, index) => {
            const initialPos = ctx.initialPositions[index];
            if (!initialPos) {
                return;
            }
            const dx = ctx.pointer.x - initialPos.initialLeft;
            const dy = ctx.pointer.y - initialPos.initialTop;

            clone.style.transform = `translate(${dx}px, ${dy}px)`;
            clone.style.width = `${width}px`;
            clone.style.height = `${height}px`;
        });
    },
});
