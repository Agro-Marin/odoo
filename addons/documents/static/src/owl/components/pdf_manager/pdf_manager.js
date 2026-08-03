/** @odoo-module native */
import { ExitSplitToolsDialog } from "@documents/owl/components/pdf_exit_dialog/pdf_exit_dialog";
import { PdfGroupName } from "@documents/owl/components/pdf_group_name/pdf_group_name";
import {
    makePdfPageStoreData,
    PdfPageStore,
} from "@documents/owl/components/pdf_manager/pdf_page_store";
import { PdfPage } from "@documents/owl/components/pdf_page/pdf_page";
import { Component, onWillStart, toRaw, useEffect, useRef, useState } from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown";
import { _t } from "@web/core/translation";
import { uniqueId } from "@web/core/utils/functions";
import { useService } from "@web/core/utils/hooks";
import { loadPDFJS, pdfjsLib } from "@web/core/utils/pdfjs";
import { useCommand } from "@web/ui/commands";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
import { useActiveElement } from "@web/ui/ui_service";
import { ConfirmationDialog, Dialog } from "@web/ui/dialog";

const BLANK_PAGE_THRESHOLD = 2500;
const BLANK_PIXEL_FILTER_VALUE = 220;
/** Menu entries that open an overlay over the app rather than navigating away. */
const NON_LEAVING_MENUS = ["shortcuts", "settings", "support", "documentation"];

export class PdfManager extends Component {
    static components = {
        Dialog,
        Dropdown,
        PdfPage,
        PdfGroupName,
    };
    static defaultProps = {
        embeddedActions: [],
    };
    static props = {
        documents: Array,
        embeddedActions: { type: Array, optional: true },
        onProcessDocuments: { type: Function },
        close: { type: Function },
    };
    static template = "documents.component.PdfManager";

    setup() {
        this.root = useRef("root");
        //setting the active element allows restricting the command palette to the context of this Component
        //this is necessary because this Component is a modal in disguise but does not properly override "Dialog"
        useActiveElement("root");
        this.pageViewer = useRef("pageViewer");
        this.pagePreview = useRef("pagePreview");
        this.selectionBox = useRef("selectionBox");
        this.addFileInput = useRef("addFileInput");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        // Page/group bookkeeping (pages, groups, ordering, page count, focus and
        // last selection) belongs to the store, which is the only thing allowed
        // to mutate it. `useState` supplies the reactivity; the store's own
        // logic knows nothing about the proxy. Nothing non-serialisable goes in
        // there — see `pageCanvases` below, which stays out for that reason.
        this.store = new PdfPageStore(useState(makePdfPageStoreData()));
        this.state = useState({
            // Disables upload button if currently uploading.
            uploadingLock: false,
            // object pageCanvases[pageId] = { canvas, pageObject }
            pageCanvases: {},
            // The page that is open as large preview.
            viewedPage: undefined,
            // The page's name that is open as large preview.
            viewedPageName: undefined,
            // The page's index that is open as large preview.
            viewedPageIndex: undefined,
            // whether to archive the original documents.
            archive: true,
            // Whether to keep the document(s) or not.
            keepDocument: true,
            //name of the opened document
            fileName: "",
            // edit on group name
            edit: false,
            isSelecting: false,
            selectionBoxArgs: { left: "0px", top: "0px", width: "0px", height: "0px" },
        });

        this._exitSplitToolsClick = false;
        this._newFiles = {};
        this._selectionX = 0.0;
        this._selectionY = 0.0;
        this._selectionScrollTop = 0.0;
        this._selectionScrollLeft = 0.0;
        this._embeddedActionApplied = false;
        this._onMouseDown = this._onMouseDown.bind(this);
        this._onMouseUp = this._onMouseUp.bind(this);
        this._onMouseMove = this._onMouseMove.bind(this);
        this._onShiftDown = this._onShiftDown.bind(this);
        this._setUseCommand = this._setUseCommand.bind(this);
        this._exitSplitTools = this._exitSplitTools.bind(this);
        // Resources to release on unmount: object URLs created from uploaded
        // files, and pdf.js document proxies (which hold worker-side state).
        this._objectUrls = [];
        this._pdfDocuments = [];

        onWillStart(async () => {
            await this._loadAssets();
        });

        useEffect(
            () => {
                const _onOutsideClick = this._onOutsideClick.bind(this);
                if (this.props.documents.length === 1) {
                    this.state.fileName = this._removePdfExtension(
                        this.props.documents[0].name,
                    );
                }
                for (const pdf_document of this.props.documents) {
                    this._addFile(pdf_document.name, {
                        url: `/documents/content/${encodeURIComponent(pdf_document.access_token)}`,
                        documentId: pdf_document.id,
                    });
                }
                document.addEventListener("click", _onOutsideClick, true);
                document.addEventListener("mousedown", this._onMouseDown, true);
                document.addEventListener("mouseup", this._onMouseUp, true);
                document.addEventListener("mousemove", this._onMouseMove, true);
                document.addEventListener("keydown", this._onShiftDown, true);
                return () => {
                    document.removeEventListener("click", _onOutsideClick, true);
                    document.removeEventListener("mousedown", this._onMouseDown, true);
                    document.removeEventListener("mouseup", this._onMouseUp, true);
                    document.removeEventListener("mousemove", this._onMouseMove, true);
                    document.removeEventListener("keydown", this._onShiftDown, true);
                    // Release object URLs and pdf.js worker documents so exiting
                    // the tool (especially with pages still loaded) does not leak.
                    for (const objectUrl of this._objectUrls) {
                        URL.revokeObjectURL(objectUrl);
                    }
                    for (const pdf of this._pdfDocuments) {
                        pdf.destroy();
                    }
                    this._objectUrls = [];
                    this._pdfDocuments = [];
                };
            },
            () => [],
        );

        // Shortcuts and navigation
        this._setUseCommand(
            _t("Focus previous page"),
            this._focusNextPage.bind(this, "left", false),
            "arrowleft",
            {
                allowRepeat: true,
            },
        );
        this._setUseCommand(
            _t("Focus next page"),
            this._focusNextPage.bind(this, "right", false),
            "arrowright",
            {
                allowRepeat: true,
            },
        );
        this._setUseCommand(
            _t("Focus first page of previous group"),
            this._focusNextGroup.bind(this, "left"),
            "control+ArrowLeft",
        );
        this._setUseCommand(
            _t("Focus first page of next group"),
            this._focusNextGroup.bind(this, "right"),
            "control+ArrowRight",
        );
        this._setUseCommand(
            _t("Select focused page"),
            this._spaceKeySelect.bind(this),
            "control+space",
            {
                allowRepeat: true,
            },
        );
        this._setUseCommand(
            _t("Select/Deselect all pages"),
            this._selectAll.bind(this),
            "control+a",
        );
        this._setUseCommand(
            _t("Select previous page"),
            this._focusNextPage.bind(this, "left", true),
            "shift+ArrowLeft",
            {
                allowRepeat: true,
            },
        );
        this._setUseCommand(
            _t("Select next page"),
            this._focusNextPage.bind(this, "right", true),
            "shift+ArrowRight",
            {
                allowRepeat: true,
            },
        );
        this._setUseCommand(
            _t("Select previous pages of the group"),
            this._selectUntilSplit.bind(this, "left"),
            "control+shift+ArrowLeft",
        );
        this._setUseCommand(
            _t("Select next pages of the group"),
            this._selectUntilSplit.bind(this, "right"),
            "control+shift+ArrowRight",
        );
        this._setUseCommand(
            _t("Escape Preview/Deselect/Exit"),
            this._onPushExit.bind(this),
            "escape",
        );
        this._setUseCommand(
            _t("Split selected pages"),
            this._splitSelectionHandler.bind(this),
            "control+s",
            {
                allowRepeat: true,
            },
        );
        this._setUseCommand(
            _t("Split all white pages"),
            this._splitWhitePagesHandler.bind(this),
            "shift+s",
        );
        this._setUseCommand(
            _t("Delete focused or selected pages"),
            this.onArchive.bind(this),
            "alt+backspace",
        );
        useHotkey("ArrowDown", this._focusNextPage.bind(this, "down", false), {
            allowRepeat: true,
        });
        useHotkey("ArrowUp", this._focusNextPage.bind(this, "up", false), {
            allowRepeat: true,
        });
        useHotkey("shift+ArrowDown", this._focusNextPage.bind(this, "down", true), {
            allowRepeat: true,
        });
        useHotkey("shift+ArrowUp", this._focusNextPage.bind(this, "up", true), {
            allowRepeat: true,
        });
        useHotkey("enter", this._togglePreviewer.bind(this), {
            allowRepeat: true,
        });
        useHotkey("delete", this.onArchive.bind(this));
    }

    /**
     * Set the useCommand hook for shortcuts
     * @param {String} name
     * @param {Function} callback
     * @param {String} hotkey
     * @param {Object} options
     * @private
     */
    _setUseCommand(name, callback, hotkey, options) {
        useCommand(name, callback, {
            category: "smart_action",
            hotkey: hotkey,
            hotkeyOptions: options,
        });
    }

    //--------------------------------------------------------------------------
    // Getters / Setters
    //--------------------------------------------------------------------------

    /**
     * @return {String[]}
     */
    get ignoredPageIds() {
        return this.store.ignoredPageIds;
    }
    /**
     * @return {String[]}
     */
    get selectedPageIds() {
        return this.store.selectedPageIds;
    }
    /**
     * @return {Boolean}
     */
    get isDebugMode() {
        return Boolean(this.env.debug);
    }
    /**
     * @return {Boolean}
     */
    get allSelected() {
        return this.store.allSelected;
    }
    /**
     * @return {String[]}
     */
    get sortedPagesIds() {
        return this.store.sortedPageIds;
    }

    //----------------------------------------------------------------------
    // Handlers
    //----------------------------------------------------------------------

    /**
     * Enter or leave the group-name edit mode.
     *
     * Selection-neutral on purpose: this runs on entering the input *and* on
     * leaving it (blur, Enter), so toggling the selection here would undo what the
     * click that opened the input just did.
     * @public
     * @param {String} groupId
     * @param {Boolean} toggle
     */
    onToggleEdit(groupId, toggle) {
        this.state.edit = toggle ? groupId : false;
    }
    /**
     * Clicking a group's name selects the whole group (or deselects it if it
     * already is fully selected) and opens the rename input.
     * @public
     * @param {String} groupId
     */
    onClickGroupName(groupId) {
        this.store.toggleGroupSelection(groupId);
        this.store.focusedPage = undefined;
        this.onToggleEdit(groupId, true);
    }
    /**
     * Returns the number of cards per line
     * @private
     */
    _computeCardsPerLine() {
        const allPages = [...document.querySelectorAll(".o_documents_pdf_page_frame")];
        if (!allPages.length) {
            // No card rendered yet (arrow key pressed before the first PDF
            // finished loading, or after a load failure): nothing to measure.
            return 1;
        }
        const top = allPages[0].getBoundingClientRect().top;
        return allPages.filter((page) => page.getBoundingClientRect().top === top)
            .length;
    }
    /**
     * Deselect every page
     * @private
     */
    _unSelectPages() {
        this.store.unselectAll();
    }
    /**
     * Handles the activation/desactivation of the splitters in the active pages
     * @private
     */
    _splitSelectionHandler() {
        if (this.state.viewedPage) {
            return;
        }
        const selectedPages = this.selectedPageIds;
        const focusedPageisSelected = selectedPages.includes(this.store.focusedPage);
        const sortedPagesIds = this.sortedPagesIds;
        if (this.store.focusedPage && !focusedPageisSelected) {
            const indexPage = sortedPagesIds.indexOf(this.store.focusedPage);
            const previousPageId = sortedPagesIds[indexPage - 1];
            if (indexPage !== 0) {
                this.store.toggleSeparator(
                    previousPageId,
                    this.store.getPage(previousPageId).groupId,
                );
            }
            return;
        }
        let toggleSeparatorBool = true;
        const pagesToSplit = [];
        const pagesToGather = [];
        for (const pageId of selectedPages) {
            const indexPage = sortedPagesIds.indexOf(pageId);
            if (
                indexPage < sortedPagesIds.length - 1 &&
                this.store.getPage(sortedPagesIds[indexPage + 1]).isSelected
            ) {
                // Asked of the store, not scraped off the rendered splitter: the
                // class agrees by construction, but only the store is right before
                // the DOM has rendered.
                const isSeparatorActive = this.store.isLastPageOfGroup(pageId);
                toggleSeparatorBool = toggleSeparatorBool && isSeparatorActive;
                if (isSeparatorActive) {
                    pagesToGather.push(this.store.getPage(pageId));
                } else {
                    pagesToSplit.push(this.store.getPage(pageId));
                }
            }
        }
        const pagesToTreat = toggleSeparatorBool ? pagesToGather : pagesToSplit;
        for (const page of pagesToTreat) {
            this.store.toggleSeparator(page.pageId, page.groupId);
        }
    }
    /**
     * Handles the split of all the whites pages in the document.
     * This method will traverse all the pages sequentially and create groups
     * delimited by a (or some) white page(s). It will ease the user experience
     * when processing scanned documents.
     */
    async _splitWhitePagesHandler() {
        if (this.store.groupIds.length > 1) {
            // Destructive and undoable: it throws away every group the user has
            // built so far. Only ask when there is actually something to lose
            // (a single group is the untouched initial state).
            this.dialog.add(ConfirmationDialog, {
                title: _t("Split on blank pages"),
                body: _t(
                    "This will discard the current grouping and rebuild the groups from the blank pages. This cannot be undone.",
                ),
                confirm: () => this._splitWhitePages(),
                cancel: () => {},
            });
            return;
        }
        await this._splitWhitePages();
    }
    /**
     * Actual blank-page splitting, without the confirmation step.
     * @private
     */
    async _splitWhitePages() {
        this.store.splitOnBlankPages({
            blankName: _t("Blank Page"),
            subDocName: (count) => _t("sub-doc-%s", count),
        });
    }
    /**
     * Add pdf file inside the split tools
     * @private
     * @param {String} name
     * @param {Object} param1
     * @param {number} [param1.documentId] the id of the `documents.document` record.
     * @param {Object} [param1.file]
     * @param {String} [param1.url]
     */
    async _addFile(name, { documentId, file, url }) {
        let objectUrl;
        if (!url) {
            if (!file && !documentId) {
                return;
            }
            url = objectUrl = URL.createObjectURL(file);
            this._objectUrls.push(url);
        }
        const displayName = name;
        this.state.uploadingLock = true;
        const fileId = uniqueId("file");
        try {
            const pdf = await this._getPdf(url);

            if (file) {
                this._newFiles[fileId] = { type: "file", file };
            } else if (documentId) {
                this._newFiles[fileId] = { type: "document", documentId };
            }
            if (this._newFiles[fileId]) {
                // Keep the per-file resources so `_removeFile` can release them
                // as soon as the file is fully consumed, instead of holding a
                // worker-side document alive until the whole tool is closed.
                this._newFiles[fileId].pdf = pdf;
                this._newFiles[fileId].objectUrl = objectUrl;
            }
            name = this._removePdfExtension(name || _t("New File"));

            const pageCount = pdf.numPages;
            const { pageIds, newPages } = this.store.createPagesForFile({
                fileId,
                name,
                pageCount,
                // A single document is exploded page by page; several documents
                // each keep one group.
                groupPerPage: this.props.documents.length <= 1,
            });
            // Canvases stay out of the store: they are DOM nodes and pdf.js
            // page proxies, which have no business inside a reactive.
            for (const pageId of pageIds) {
                this.state.pageCanvases[pageId] = {};
            }
            this._newFiles[fileId].pageIds = this._newFiles[fileId].selectedPageIds =
                pageIds;
            this.state.uploadingLock = false;

            await this._loadCanvases({ newPages, pageCount, pdf });
        } catch (error) {
            // pdf.js rejects on encrypted (PasswordException), corrupt
            // (InvalidPDFException) and unreachable (Missing/UnexpectedResponse)
            // PDFs. Unhandled, that reaches the global error handler and leaves
            // `uploadingLock` on, disabling every top-bar button.
            this._displayErrorNotification(
                error?.name === "PasswordException"
                    ? _t("%s is password protected and cannot be split.", displayName)
                    : _t("Could not open %s.", displayName),
            );
            if (objectUrl) {
                URL.revokeObjectURL(objectUrl);
                this._objectUrls = this._objectUrls.filter(
                    (each) => each !== objectUrl,
                );
            }
        } finally {
            this.state.uploadingLock = false;
        }
    }
    /**
     * @private
     * @param {String} message
     */
    _displayErrorNotification(message) {
        this.notification.add(message, {
            type: "danger",
        });
    }
    /**
     * @private
     * @param {number} number
     */
    _displayNumberCreatedDocuments(number) {
        this.notification.add(_t("%s new document(s) created", number), {
            type: "success",
        });
    }
    /**
     * @private
     * @param {number} number
     */
    _displayNumberDeletedPages(number) {
        this.notification.add(_t("%s page(s) deleted", number), { type: "success" });
    }
    /**
     * Ignored pages are not committed but are instead kept in the
     * PDF Manager. If no ignored page remain, the PDF Manager closes and the
     * view is reloaded.
     * @private
     * @param {number} [actionId]
     */
    async _applyChanges(actionId) {
        let processedPageIds = this.selectedPageIds;
        let pageIds = this.ignoredPageIds;
        if (processedPageIds.length === 0 && !this.store.focusedPage) {
            this._displayErrorNotification(_t("No document has been selected"));
            return;
        }
        if (processedPageIds.length === 0) {
            processedPageIds = [this.store.focusedPage];
            pageIds = pageIds.filter((pageId) => pageId !== this.store.focusedPage);
        }
        const exit = !pageIds.length;

        let fileName = _t("Remaining Pages");
        if (this.state.fileName) {
            fileName = this.state.fileName + " " + fileName;
        }
        try {
            const documentIds = await this._sendChanges();
            await this.props.onProcessDocuments({ documentIds, actionId, exit });
            this._displayNumberCreatedDocuments(documentIds.length);
            if (!exit) {
                this._embeddedActionApplied = true;
                // The store releases the focus / last-selection references of
                // every page it detaches, so a committed page (which survives
                // in `pages` while its file still has uncommitted pages) can
                // never be handed group-less to code expecting a group.
                for (const pageId of processedPageIds) {
                    this._removePage(pageId, { fromFile: true });
                }
            } else {
                this.props.close();
            }
        } catch (error) {
            this._displayErrorNotification(error.message || error);
            if (pageIds.length) {
                this.store.createGroup({ name: fileName, pageIds, isSelected: true });
            }
        } finally {
            this.state.uploadingLock = false;
        }
    }

    /**
     * This method will check if the page contains any text (for computer
     * generated pdf) and for the image pixels if it's a scanned pdf.
     */
    async _isBlankPage(page, canvas) {
        const pageContent = await page.getTextContent();
        const hasText = pageContent.items.length > 0;
        return !hasText && this._hasBlankGraphics(canvas);
    }

    /**
     * This method will check the canvas for each pixel based on its color.
     * If the sum of all the color code for each pixel doesn't exceed the
     * empirically tested threshold the image is considered as blank.
     * It's used to detect scanned blank page (they are never really empty...)
     *
     * Walks RGB and steps over the alpha byte `getImageData` interleaves: pdf.js
     * paints onto an opaque fill, so alpha is always 255 and testing it is a
     * quarter of the bytes scanned for nothing (295ms -> 132ms over 400 pages at
     * the 160x230 size this renders).
     */
    _hasBlankGraphics(canvas) {
        const pixels = canvas
            .getContext("2d")
            .getImageData(0, 0, canvas.width, canvas.height, {
                colorSpace: "display-p3",
            }).data;
        let totalSum = 0;
        for (let i = 0; i < pixels.length; i += 4) {
            for (let channel = 0; channel < 3; channel++) {
                const value = pixels[i + channel];
                if (value < BLANK_PIXEL_FILTER_VALUE) {
                    totalSum += 255 - value;
                    if (totalSum >= BLANK_PAGE_THRESHOLD) {
                        return false;
                    }
                }
            }
        }
        return true;
    }

    /**
     * To be overwritten in tests (along with _renderCanvas()).
     * @private
     * @param {String} url
     * @return {PdfJsObject} pdf
     *    should be constructed as follow:
     *        pdf.getPage(pageNumber) {function} return {pageObject}
     *        pdf.numPages {number}
     */
    async _getPdf(url) {
        const pdf = await pdfjsLib.getDocument(url).promise;
        this._pdfDocuments.push(pdf);
        return pdf;
    }
    /**
     * To be overwritten in tests.
     * @private
     */
    async _loadAssets() {
        await loadPDFJS();
    }
    /**
     * @private
     * @param {Object} [param0]
     * @param {Object} [param0.newPages]
     * @param {number} [param0.pageCount]
     * @param {PdfjsObject} [param0.pdf]
     */
    async _loadCanvases({ newPages, pageCount, pdf }) {
        for (let pageNumber = 1; pageNumber <= pageCount; pageNumber++) {
            if (!this.root.el) {
                break;
            }
            const pageId = newPages[pageNumber];
            const page = await pdf.getPage(pageNumber);
            const canvas = await this._renderCanvas(toRaw(page), {
                width: 160,
                height: 230,
            });
            this.state.pageCanvases[pageId] = { page, canvas };
            const storePage = this.store.getPage(pageId);
            if (storePage) {
                storePage.isBlank = await this._isBlankPage(page, canvas);
            }
        }
    }
    /**
     * @private
     * @param {Object} page
     * @param {Object} param1
     * @param {number} param1.width
     * @param {number} param1.height
     * @return {DomElement} canvas
     */
    async _renderCanvas(page, { width, height }) {
        const viewPort = page.getViewport({ scale: 1 });
        const isLandscape = viewPort.width > viewPort.height;
        const canvas = document.createElement("canvas");
        canvas.className = "o_documents_pdf_canvas";
        canvas.width = width;
        canvas.height = height;
        const scale = isLandscape
            ? Math.min(canvas.width / viewPort.height, canvas.height / viewPort.width)
            : Math.min(canvas.width / viewPort.width, canvas.height / viewPort.height);
        await page.render({
            canvasContext: canvas.getContext("2d"),
            viewport: page.getViewport({
                scale,
                rotation: isLandscape ? 270 : viewPort.rotation,
            }),
        }).promise;
        return canvas;
    }
    /**
     * Endpoint of the manager, sends the page structure to be split to the
     * server and closes the manager.
     * @private
     */
    async _sendChanges() {
        this.state.uploadingLock = true;
        const fileIds = [];
        const files = [];
        for (const key in this._newFiles) {
            if (this._newFiles[key].type === "file") {
                files.push(this._newFiles[key].file);
                fileIds.push(key);
            }
        }
        const fileGroups = Object.values(
            JSON.parse(JSON.stringify(this.store.groupData)),
        );
        let activePages = this.selectedPageIds;
        if (!activePages.length) {
            // An array, not a bare string: `activePages` feeds `.includes(pageId)`
            // below, where a string would match substrings ("page2" -> "page25").
            activePages = this.store.focusedPage ? [this.store.focusedPage] : [];
            this.store.focusedPage = false;
        }
        for (const group of fileGroups) {
            group.pageIds = group.pageIds.filter((page) => activePages.includes(page));
        }
        const newFiles = fileGroups.filter((group) => group.pageIds.length > 0);
        for (const newFile of newFiles) {
            newFile.new_pages = [];
            for (const pageId of newFile.pageIds) {
                const page = this.store.getPage(pageId);
                const file = this._newFiles[page.fileId];
                const old_file_type = file.type;
                const old_file_index =
                    old_file_type === "file"
                        ? fileIds.indexOf(page.fileId)
                        : file.documentId;
                newFile.new_pages.push({
                    old_file_type,
                    old_file_index,
                    old_page_number: page.localPageNumber,
                });
            }
            delete newFile.pageIds;
        }
        // When splitting a file we want them displayed in the same order as they were in the file.
        newFiles.reverse();
        // Http request
        const sourceDocument = this.props.documents[0];
        const data = new FormData();
        data.append("csrf_token", odoo.csrf_token);
        for (const file of files) {
            data.append("ufile", file);
        }
        data.append("new_files", JSON.stringify(newFiles));
        data.append("archive", this.state.archive);
        data.append(
            "vals",
            JSON.stringify({
                folder_id: sourceDocument.folder_id?.id ?? false,
                tag_ids: sourceDocument.tag_ids.currentIds,
                owner_id: sourceDocument.owner_id.id,
                partner_id: sourceDocument.partner_id.id,
                active: this.state.keepDocument,
            }),
        );
        const response = await fetch("/documents/pdf_split", {
            method: "post",
            body: data,
        });
        if (!response.ok) {
            throw new Error(_t("PDF split failed (status %s).", response.status));
        }
        return response.json();
    }
    /**
     * Detach a page from its group, and optionally release the file resources
     * it was the last consumer of.
     * @private
     * @param {String} pageId
     * @param {Object} [param1]
     * @param {boolean} [param1.fromFile] whether to remove page from the file, in which case
     * the file will be removed if none of its pages are used.
     */
    _removePage(pageId, { fromFile } = {}) {
        const page = this.store.getPage(pageId);
        if (!page) {
            return;
        }
        // The store tolerates an already-detached page (committed by a partial
        // split, say) and clears any focus reference to it.
        this.store.removePage(pageId);
        if (fromFile && page.fileId && this._newFiles[page.fileId]) {
            const selectedPageIds = this._newFiles[page.fileId].selectedPageIds;
            this._newFiles[page.fileId].selectedPageIds = selectedPageIds.filter(
                (number) => number !== pageId,
            );
            if (this._newFiles[page.fileId].selectedPageIds.length === 0) {
                this._removeFile(page.fileId);
            } else {
                // Release this committed page's canvas/pdf-page proxy now instead
                // of keeping every page of the file alive until it is fully
                // consumed.
                delete this.state.pageCanvases[pageId];
            }
            page.fileId = false;
        }
    }
    /**
     * @private
     * @param {String} fileId
     */
    _removeFile(fileId) {
        const fileData = this._newFiles[fileId];
        if (!fileData) {
            return;
        }
        for (const pageId of fileData.pageIds || []) {
            delete this.state.pageCanvases[pageId];
            this.store.deletePage(pageId);
        }
        // The file is fully consumed: release its worker-side pdf.js document
        // and its object URL now rather than waiting for the unmount cleanup.
        if (fileData.pdf) {
            fileData.pdf.destroy();
            this._pdfDocuments = this._pdfDocuments.filter(
                (pdf) => pdf !== fileData.pdf,
            );
        }
        if (fileData.objectUrl) {
            URL.revokeObjectURL(fileData.objectUrl);
            this._objectUrls = this._objectUrls.filter(
                (url) => url !== fileData.objectUrl,
            );
        }
        delete this._newFiles[fileId];
    }
    /**
     * use to remove .pdf extention from file name
     * @private
     * @param {String} name
     */
    _removePdfExtension(name) {
        return name.replace(/\.pdf$/gi, "");
    }
    /**
     * Opens the exit dialog
     * @private
     */
    _exitSplitTools(formerTargetCallback = () => {}) {
        this.dialog.add(ExitSplitToolsDialog, {
            isEmbeddedActionApplied: this._embeddedActionApplied,
            onDeleteRemainingPages: async () => {
                await this.props.close();
                formerTargetCallback();
            },
            onGatherRemainingPages: async () => {
                await this._exitByGatheringRemainingPages();
                formerTargetCallback();
            },
            close: () => {},
        });
    }
    /**
     * Gather the remaining pages so they are kept into one document that is sent to the backend
     * @private
     */
    async _exitByGatheringRemainingPages() {
        this.store.regroupAll({
            name: this.state.fileName
                ? _t("%s (remaining pages)", this.state.fileName)
                : _t("Remaining Pages"),
            isSelected: true,
        });
        await this._applyChanges();
    }
    /**
     * Adapt the scroll of the page viewer in order to keep the focused page visible
     * @private
     */
    _keepFocusedPageInScreen() {
        if (!this.store.focusedPage || !this.pageViewer.el) {
            return;
        }
        // CSS.escape: the page id is interpolated raw into a selector, so an
        // unquoted/unescaped value throws a SyntaxError instead of returning null.
        const card = document.querySelector(
            `[data-id="${CSS.escape(this.store.focusedPage)}"]`,
        );
        if (!card) {
            // Focus set before the card exists (arrow key pressed while the PDF
            // is still loading, or after a load failure).
            return;
        }
        const focusedCardCoordinates = card.getBoundingClientRect();
        const pageViewerCoordinates = this.pageViewer.el.getBoundingClientRect();
        const bottomDifference =
            focusedCardCoordinates.bottom - pageViewerCoordinates.bottom;
        const topDifference = focusedCardCoordinates.top - pageViewerCoordinates.top;
        // 60 and 10 are harcoded values to improve the UI when scrolling.
        if (bottomDifference > 0) {
            this.pageViewer.el.scrollBy(0, bottomDifference + 60);
        }
        if (topDifference < 0) {
            this.pageViewer.el.scrollBy(0, topDifference - 10);
        }
    }

    //----------------------------------------------------------------------
    // Keyboard events and handlers
    //----------------------------------------------------------------------

    /**
     * On shift pressed, the focused page is selected
     * @private
     * @param {Event} ev
     */
    _onShiftDown(ev) {
        if (document.activeElement.classList.contains("o_pdf_name_input")) {
            // Do NOT stopPropagation here: this is a capture-phase listener on
            // document, so it would prevent the rename input's own keydown
            // handler (Enter to commit/exit) from ever running. The manager's
            // command/hotkey shortcuts are already suppressed while an editable
            // element is focused (editable protection), so simply bail out.
            return;
        }
        if (
            ev.key === "Shift" &&
            !ev.metaKey &&
            !ev.ctrlKey &&
            !ev.altKey &&
            !this.state.viewedPage &&
            this.store.focusedPage
        ) {
            this.store.toggleSelected(this.store.focusedPage);
        }
    }
    /**
     * Focus next targetted page
     * @private
     * @param {String} direction
     * @param {Boolean} doSelect
     */
    _focusNextPage(direction, doSelect) {
        if (this.state.viewedPage) {
            if (direction === "left") {
                this.onClickPrevious();
            }
            if (direction === "right") {
                this.onClickNext();
            }
            return;
        }
        // `_computeCardsPerLine` is the component's business (it measures the
        // rendered cards); the store only asks for it when it needs the stride.
        this.store.focusNextPage(direction, doSelect, () =>
            this._computeCardsPerLine(),
        );
        this._keepFocusedPageInScreen();
    }
    /**
     * Focus the first page of the next tragetted group
     * @private
     * @param {String} direction
     */
    _focusNextGroup(direction) {
        if (this.state.viewedPage) {
            return;
        }
        this.store.focusNextGroup(direction);
        this._keepFocusedPageInScreen();
    }
    /**
     * Opens or closes the previewer
     * @private
     */
    _togglePreviewer() {
        if (this.store.focusedPage && !this.state.viewedPage) {
            this.onClickPage(this.store.focusedPage);
        }
        if (this.store.focusedPage && this.state.viewedPage) {
            this._onPushExit();
        }
    }
    /**
     * On space key pressed, toogles the focused page
     * @private
     */
    _spaceKeySelect() {
        if (this.store.focusedPage && !this.state.viewedPage) {
            this.store.toggleSelected(this.store.focusedPage);
        }
    }
    /**
     * select all the pages from focused page until beginning/end
     * of the group according to the arrow key pressed
     * @private
     * @param {String} direction
     */
    _selectUntilSplit(direction) {
        if (this.state.viewedPage) {
            return;
        }
        this.store.selectUntilSplit(direction);
    }
    /**
     * (De)select all active pages
     * @private
     */
    _selectAll() {
        if (this.state.viewedPage) {
            return;
        }
        this.store.toggleSelectAll();
    }
    /**
     * Exit key pressing behaviour :
     * - Exit previewer
     * - Deselect pages
     * - Loose focus
     * - Exit split tools
     * @private
     */
    _onPushExit() {
        // If we are in the previewer, exit the previewer and focus on previewed page
        if (this.state.viewedPage) {
            this.store.focusedPage = this.state.viewedPage;
            this.previewCanvas = undefined;
            this.state.viewedPage = undefined;
            return;
        }
        // Deselect selected pages
        if (this.selectedPageIds.length) {
            this._unSelectPages();
            return;
        }
        // If one page is focus, loose the focus
        if (this.store.focusedPage) {
            this.store.focusedPage = undefined;
            return;
        }
        this._exitSplitTools();
    }

    //--------------------------------------------------------------------------
    // Click events and handlers
    //--------------------------------------------------------------------------
    /**
     * @private
     * @param {Event} ev
     */
    _onMouseDown(ev) {
        if (
            ev.target.closest(".o_pdf_page") ||
            ev.target.closest(".o_page_splitter_wrapper") ||
            ev.target.closest(".o_documents_pdf_manager_top_bar") ||
            ev.target.closest(".o_main_navbar") ||
            ev.target.closest(".o_documents_pdf_page_preview") ||
            ev.target.closest(".o_pdf_group_name_block") ||
            ev.button !== 0 // Main button pressed, usually the left button or the un-initialized state
        ) {
            return;
        }
        this._selectionX = ev.pageX;
        this._selectionY = ev.pageY - 40;
        this._selectionScrollTop = this.pageViewer.el.scrollTop;
        this._selectionScrollLeft = this.pageViewer.el.scrollLeft;
        this.state.selectionBoxArgs["left"] = this._selectionX + "px";
        this.state.selectionBoxArgs["top"] = this._selectionY + "px";
        this.state.selectionBoxArgs["width"] = 0 + "px";
        this.state.selectionBoxArgs["height"] = 0 + "px";
        this.state.isSelecting = true;
        if (!ev.ctrlKey && !ev.metaKey && !ev.shiftKey) {
            if (!this.selectedPageIds.length) {
                this.store.focusedPage = undefined;
            }
            this.state.edit = false;
            this._unSelectPages();
        }
    }
    /**
     * On mouse move, the selection area expends according the cursor position
     * If selection area enters into a page, the latter is selected except if shift key is pressed.
     * In this case, it is unSelected
     * @private
     * @param {Event} ev
     */
    _onMouseMove(ev) {
        if (!this.state.isSelecting) {
            return;
        }
        this.store.focusedPage = false;
        const x = ev.pageX;
        const y = ev.pageY - 40;
        const scrollTopDiff = this.pageViewer.el.scrollTop - this._selectionScrollTop;
        const scrollLeftDiff =
            this.pageViewer.el.scrollLeft - this._selectionScrollLeft;
        this.state.selectionBoxArgs["left"] =
            x - this._selectionX + scrollLeftDiff < 0
                ? x + "px"
                : this._selectionX - scrollLeftDiff + "px";
        this.state.selectionBoxArgs["top"] =
            y - this._selectionY + scrollTopDiff < 0
                ? y + "px"
                : this._selectionY - scrollTopDiff + "px";
        this.state.selectionBoxArgs["width"] =
            Math.abs(x - (this._selectionX - scrollLeftDiff)) + "px";
        this.state.selectionBoxArgs["height"] =
            Math.abs(y - (this._selectionY - scrollTopDiff)) + "px";

        const boxCoordinates = this.selectionBox.el.getBoundingClientRect();
        const boxTop = boxCoordinates.top;
        const boxBottom = boxTop + boxCoordinates.height;
        const boxLeft = boxCoordinates.left;
        const boxRight = boxLeft + boxCoordinates.width;
        // Scoped to this manager's page viewer rather than the whole document.
        // `.o_pdf_page` is rendered only by PdfPage, which only PdfManager
        // mounts, so this is not a correctness fix -- it bounds the selector
        // scan to the subtree that can possibly match, on a handler that runs
        // on every mousemove of a drag-select.
        const cards = this.pageViewer.el.querySelectorAll(".o_pdf_page");
        for (const card of cards) {
            const cardCoordinates = card.getBoundingClientRect();
            const cardTop = cardCoordinates.top;
            const cardBottom = cardTop + cardCoordinates.height;
            const cardLeft = cardCoordinates.left;
            const cardRight = cardLeft + cardCoordinates.width;

            if (
                boxLeft < cardRight &&
                boxRight > cardLeft &&
                boxTop < cardBottom &&
                boxBottom > cardTop
            ) {
                this.store.setSelected(card.dataset.id, !ev.shiftKey);
            } else if (!ev.metaKey && !ev.ctrlKey && !ev.shiftKey) {
                this.store.setSelected(card.dataset.id, false);
            }
        }
    }
    /**
     * On mouse up, end the drag-selection (the page selection itself is applied
     * in _onMouseMove while the box is being dragged).
     * @private
     */
    _onMouseUp() {
        this.state.isSelecting = false;
    }
    /**
     * @public
     * @param {number} actionId
     */
    onClickEmbeddedAction(actionId) {
        this._applyChanges(actionId);
    }
    /**
     * @public
     */
    onClickSplit() {
        this.state.keepDocument = true;
        this._applyChanges();
    }
    /**
     * @public
     * @param {MouseEvent} ev
     */
    onClickArchive(ev) {
        ev.target.blur();
        this.state.archive = !this.state.archive;
    }
    /**
     * @public
     */
    onClickGlobalAdd() {
        this.addFileInput.el.click();
    }
    /**
     * @public
     */
    async onArchive() {
        let pagesToDelete = this.selectedPageIds;
        if (
            pagesToDelete.length === 0 &&
            !this.store.focusedPage &&
            !this.state.viewedPage
        ) {
            this._displayErrorNotification(_t("No document has been selected"));
            return;
        }
        const sortedPagesIds = this.sortedPagesIds;
        let messageInput = _t(
            "Are you sure that you want to delete the selected page(s)",
        );
        let nextFocusedPageId = pagesToDelete.includes(this.store.focusedPage)
            ? false
            : this.store.focusedPage;
        if (
            pagesToDelete.length === 0 ||
            this.state.viewedPage ||
            (this.store.focusedPage && !pagesToDelete.includes(this.store.focusedPage))
        ) {
            // A previewed page is always focused
            pagesToDelete = [this.store.focusedPage];
            messageInput = this.state.viewedPage
                ? _t("Are you sure that you want to delete this page ?")
                : _t("Are you sure that you want to delete the focused page ?");
            const focusedPageIndex = sortedPagesIds.indexOf(this.store.focusedPage);
            if (focusedPageIndex + 1 < sortedPagesIds.length) {
                nextFocusedPageId = sortedPagesIds[focusedPageIndex + 1];
            } else if (focusedPageIndex - 1 >= 0) {
                nextFocusedPageId = sortedPagesIds[focusedPageIndex - 1];
            } else {
                nextFocusedPageId = undefined;
            }
        }
        this.dialog.add(ConfirmationDialog, {
            body: messageInput,
            confirm: async () => {
                for (const pageId of pagesToDelete) {
                    this._removePage(pageId, { fromFile: true });
                }
                if (this.store.numberOfPages === 0) {
                    await this.props.onProcessDocuments({ isForcingDelete: true });
                    await this.props.close();
                }
                this._displayNumberDeletedPages(pagesToDelete.length);
                this.store.focusedPage = nextFocusedPageId;
                if (this.state.viewedPage && nextFocusedPageId) {
                    await this.onClickPage(nextFocusedPageId);
                } else {
                    this.state.viewedPage = undefined;
                }
            },
            cancel: () => {},
        });
    }
    /**
     * @public
     * @param {MouseEvent} ev
     */
    async onFileInputChange(ev) {
        this.state.fileName = "";
        if (!ev.target.files.length) {
            return;
        }
        const files = ev.target.files;
        for (const file of files) {
            await this._addFile(file.name, { file });
        }
        ev.target.value = null;
    }
    /**
     * @public
     */
    onClickExit() {
        this._exitSplitTools();
    }
    /**
     * Whether a click would navigate out of the split tool.
     *
     * The four menu entries listed open an overlay over the app instead of
     * leaving it, and a mobile dropdown is not a navigation either.
     *
     * @private
     * @param {HTMLElement} target
     * @returns {boolean}
     */
    _isLeavingClick(target) {
        if (target.closest(".o_burger_menu_content")) {
            return true;
        }
        const menuItem = target.closest(".dropdown-item");
        if (!menuItem && !target.closest(".o_menu_toggle")) {
            return false;
        }
        if (NON_LEAVING_MENUS.includes(menuItem?.dataset.menu)) {
            return false;
        }
        return !target.closest("[data-dropdown-is-mobile]");
    }
    /**
     * Ask before letting a click navigate away, then replay it.
     *
     * `_exitSplitToolsClick` guards the replay against re-entering this handler.
     * It now covers the burger-menu branch too, and is released once the replay
     * has been dispatched: the exit dialog can leave the manager mounted (the
     * "keep the remaining pages" answer commits them and stays if any are left),
     * and both of those were one-way before -- the burger branch re-prompted on
     * its own replayed click, and every later click skipped the prompt entirely.
     *
     * @private
     * @param {Event} ev
     */
    _onOutsideClick(ev) {
        if (this._exitSplitToolsClick || !this._isLeavingClick(ev.target)) {
            return;
        }
        ev.stopPropagation();
        ev.preventDefault();
        this._exitSplitTools(() => {
            this._exitSplitToolsClick = true;
            ev.target.click();
            this._exitSplitToolsClick = false;
        });
    }
    /**
     * Open the previewer
     * @public
     * @param {String} pageId
     */
    async onClickPage(pageId) {
        this.store.focusedPage = pageId;
        const page = this.state.pageCanvases[pageId].page;
        if (!page) {
            return;
        }
        // Our own ref, not a document-wide query for a class only we render.
        const ratio = 18 / 13;
        const width = this.pagePreview.el.clientWidth - (30 * window.innerWidth) / 100;
        this.previewCanvas = await this._renderCanvas(toRaw(page), {
            width: width,
            height: width * ratio,
        });
        this.state.viewedPage = pageId;
        const targetGroup = this.store.getGroupOfPage(pageId);
        this.state.viewedPageName =
            targetGroup.name + "-p" + (targetGroup.pageIds.indexOf(pageId) + 1);
        const sortedPagesIds = this.sortedPagesIds;
        this.state.viewedPageIndex = sortedPagesIds.indexOf(pageId);
    }
    /**
     * @public
     */
    async onClickPrevious() {
        if (this.state.viewedPageIndex > 0) {
            await this.onClickPage(this.sortedPagesIds[this.state.viewedPageIndex - 1]);
        }
    }
    /**
     * @public
     */
    async onClickNext() {
        if (this.state.viewedPageIndex < this.store.numberOfPages - 1) {
            await this.onClickPage(this.sortedPagesIds[this.state.viewedPageIndex + 1]);
        }
    }
    /**
     * @public
     * @param {customEvent} ev
     */
    onClickExitPreview(ev) {
        if (
            ev.target.classList.contains("o_documents_pdf_page_preview") ||
            ev.target.closest(".o_close_button")
        ) {
            this.store.focusedPage = this.state.viewedPage;
            this.previewCanvas = undefined;
            this.state.viewedPage = undefined;
        }
    }
    /**
     * select clicked page.
     * If shift key is pressed, trigger the range activation between last clicked page and current page
     * @public
     * @param {String} pageId
     * @param {Boolean} isRangeSelection
     */
    onSelectClicked(pageId, isRangeSelection) {
        this.store.clickSelect(pageId, { isRangeSelection });
    }
    /**
     * @public
     * @param {String} pageId
     * @param {String} groupId
     */
    onClickPageSeparator(pageId, groupId) {
        this.store.toggleSeparator(pageId, groupId);
    }
    /**
     * @public
     * @param {String} groupId
     * @param {String} name
     */
    onEditName(groupId, name) {
        this.store.renameGroup(groupId, name);
    }
    /**
     * @public
     * @param {customEvent} ev
     */
    onPageDragStart(ev) {
        ev.stopPropagation();
    }
    /**
     * @public
     * @param {String} ev.detail.targetPageId
     * @param {String} ev.detail.pageId
     */
    onPageDrop(targetPageId, pageId) {
        this.store.movePage(pageId, targetPageId);
    }
}
