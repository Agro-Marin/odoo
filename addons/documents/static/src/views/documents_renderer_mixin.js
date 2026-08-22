/** @odoo-module native */
import { useCommand } from "@web/ui/commands";
import { _t } from "@web/core/translation";
import { useService, useBus } from "@web/core/utils/hooks";
import {
    preprocessMany2oneChanges,
    preprocessMany2OneReferenceChanges,
    preprocessReferenceChanges,
    preprocessX2manyChanges,
} from "@web/model/relational_model";
import {
    onWillRender,
    onWillUnmount,
    onWillUpdateProps,
    useComponent,
    useExternalListener,
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

            onWillUnmount(() => this.documentService.stopRightPanelScrollObserver());

            useCommand(
                _t("Move to trash"),
                () => this.env.model.onArchive(),
                {
                    category: "smart_action",
                    hotkey: "control+m",
                    isAvailable: () =>
                        this.documentService.userIsInternal &&
                        this.hasRecordsToArchive &&
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
                        this.hasRecordsToDelete &&
                        this.env.model.canDeleteRecords
                }
            );

            const setShortcutModifier = (active) => {
                this.root?.el?.classList.toggle("o_documents_dnd_shortcut", active);
            };
            useExternalListener(window, "keydown", (ev) => {
                if (ev.key === "Control") {
                    setShortcutModifier(true);
                }
            });
            useExternalListener(window, "keyup", (ev) => {
                if (ev.key === "Control") {
                    setShortcutModifier(false);
                }
            });
            useExternalListener(window, "blur", () => setShortcutModifier(false));

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
            useBus(this.documentService.bus, "UPDATE-DOCUMENT-FOLDER", () => {
                this.documentService.focusRecord(this.getContainerRecord());
            });
        }
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
                file_size: (this.props.list?.model.fileSize || 0) * 1e6,
            });
            const config = { ...this.env.model.config, resId: data.id };
            const record = new this.env.model.constructor.Record(this.env.model, config, data);
            record.isContainer = true;

            /**
             * @override making
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
                    Object.entries(record._getChanges()).filter(([name]) =>
                        fieldsToSave.has(name)
                    )
                );
                await this.env.model.orm.write(
                    "documents.document",
                    [record.data.id],
                    changesToSave
                );
            };
            /**
             * @override to
             */
            record.load = async () => {
                await this.env.searchModel._reloadSearchPanel();
                this.component.render();
            };
            /**
             * @override skip
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

        get hasRecordsToDelete() {
            return this.documentService.userIsInternal
                ? this.selection.some((r) => !r.data.active)
                : this.selection.length > 0;
        }

        get hasRecordsToArchive() {
            return this.selection.some((r) => r.data.active);
        }
    };
