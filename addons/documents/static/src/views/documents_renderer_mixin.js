/** @odoo-module native */
import { useCommand } from "@web/services/commands/command_hook";
import { _t } from "@web/core/l10n/translation";
import { useService, useBus } from "@web/core/utils/hooks";
import {
    preprocessMany2oneChanges,
    preprocessMany2OneReferenceChanges,
    preprocessReferenceChanges,
    preprocessX2manyChanges,
} from "@web/model/relational_model/record_preprocessors";
import {
    onWillRender,
    onWillUnmount,
    onWillUpdateProps,
    useComponent,
    useEffect,
    useState,
} from "@odoo/owl";

export const DocumentsRendererMixin = (component) =>
    class extends component {
        setup() {
            super.setup();
            this.documentService = useService("document.document");
            this.notificationService = useService("notification");

            this.documentService.focusRecord(this.selection?.[0] || this.getContainerRecord(), true);
            this.rightPanelState = useState(this.documentService.rightPanelReactive);
            this.component = useComponent();
            this.refreshFocus = false;

            // The service is a singleton and its right-panel scroll observer
            // watches OUR `.o_documents_content`. Nothing else ever tears it
            // down when the conditions it waits for do not occur, so it would
            // keep a detached subtree reachable after we go.
            onWillUnmount(() => this.documentService.stopRightPanelScrollObserver());

            useCommand(
                _t("Move to trash"),
                () => this.env.model.onArchive(),
                {
                    category: "smart_action",
                    hotkey: "control+m",
                    isAvailable: () =>
                        this.documentService.userIsInternal &&
                        this.recordsToArchive &&
                        this.selection.every((r) => r.data.user_permission === "edit")
                }
            );
            useCommand(
                _t("Delete"),
                () => this.env.model.onDelete(),
                {
                    category: "smart_action",
                    hotkey: "control+d",
                    isAvailable: () =>
                        this.recordsToDelete &&
                        this.env.model.canDeleteRecords
                }
            );
            useEffect(
                () => {
                    this.recordsToDelete = !this.documentService.userIsInternal
                        ? this.selection
                        : this.selection.some((r) => !r.data.active);
                    this.recordsToArchive = this.selection.some((r) => r.data.active);
                },
                () => [this.selection]
            );

            onWillUpdateProps((nextProps) => {
                if (nextProps.list !== this.props.list) {
                    this.refreshFocus = true;
                }
            });
            onWillRender(() => {
                if (this.refreshFocus) {
                    this.refreshFocus = false;
                    this.documentService.focusRecord(this.selection?.[0] || this.getContainerRecord());
                }
            });
            useBus(this.documentService.bus, "UPDATE-DOCUMENT-FOLDER", (ev) => {
                this.documentService.focusRecord(this.getContainerRecord());
            });
        }
        /**
         * Default focus on first record (fallback on container record)
         * if there is no focused record or current focused record is out of the record list.
         */
        setDefaultFocus() {
            const focusedRecord = this.documentService.focusedRecord;
            const records = this.props.list ? this.props.list.records : this.props.records;
            if (!focusedRecord || !records.find((r) => r.id === focusedRecord.id)) {
                const record =
                    this.env.config.viewType === "kanban"
                        ? records.find((r) => r.data.type === "folder") || records[0]
                        : records[0];
                this.documentService.focusRecord(record || this.getContainerRecord(), true);
            }
            return this.documentService.focusedRecord;
        }
        /**
         * Record for showing/modifying details of containing folder
         */
        getContainerRecord() {
            const folder = this.env.searchModel.getSelectedFolder();
            const folderData = this.env.searchModel.getFolderAndParents(folder);
            const folderId =
                typeof folder.folder_id === "object"
                    ? folder.folder_id
                    : folderData?.length > 1 && typeof folderData[1].id === "number"
                    ? [folderData[1].id, folderData[1].display_name]
                    : false;

            const data = Object.assign({}, folder, {
                folder_id: folderId,
                name: folder.display_name,
                type: "folder",
                file_size: (this.props.list?.model.fileSize || 0) * 1e6, // from MB to B to be precise on single doc.
            });
            const config = { ...this.env.model.config, resId: data.id };
            const record = new this.env.model.constructor.Record(this.env.model, config, data);
            record.isContainer = true;

            /**
             * @override making sure we only save fields for which we have fetched data.
             */
            record._update = async (changes) => {
                record.dirty = true;
                const fieldsToSave = new Set(Object.keys(changes));
                await Promise.all([
                    preprocessMany2oneChanges(record, changes),
                    preprocessMany2OneReferenceChanges(record, changes),
                    preprocessReferenceChanges(record, changes),
                    preprocessX2manyChanges(record, changes),
                ]);
                record._applyChanges(changes);
                const changesToSave = Object.fromEntries(
                    Object.entries(record._getChanges()).filter(([k, _v]) => fieldsToSave.has(k))
                );
                await this.env.model.orm.write(
                    "documents.document",
                    [record.data.id],
                    changesToSave
                );
            };
            /**
             * @override to reload the document's data via the search panel update, required
             * to avoid crashes as the record is not in the view.
             */
            record.load = async () => {
                await this.env.searchModel._reloadSearchPanel();
                this.component.render();
            };
            /**
             * @override skip to avoid raising validity error for fields that
             * don't belong to the record container. Data saving is handled in our _update override.
             */
            record._save = async () => true;
            return record;
        }

        getIsDomainSelected() {
            if (this.env.model.isDomainSelected) {
                this.notificationService.add(_t("Only current page items can be dragged."), {
                    type: "info",
                });
            }
            return this.env.model.isDomainSelected;
        }

        /**
         * Number of documents in the current (container) folder
         */
        getNbViewItems() {
            if (!this.props.list) {
                return this.props.records.length;
            }
            return this.props.list.count;
        }

        get selection() {
            if (!this.props.list) {
                return this.props.records.filter((r) => r.selected);
            }
            return this.props.list.selection;
        }
    };
