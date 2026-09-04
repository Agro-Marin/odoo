// @ts-check
/** @odoo-module native */

import {
    Component,
    useState,
    onWillStart,
    useRef,
    useEffect,
    useExternalListener,
} from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardActionServiceProps } from "@web/webclient/actions";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { rpc } from "@web/core/network";
import { humanSize } from "@web/core/utils/format/binary";

const DOC_EXTS = new Set([
    "pdf",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "csv",
    "ppt",
    "pptx",
    "txt",
    "md",
]);
const CTX_MENU_W = 210;
const CTX_MENU_H = 260;

const FILE_ICONS = {
    pdf: ["fa-file-pdf-o", "text-danger"],
    doc: ["fa-file-word-o", "text-primary"],
    docx: ["fa-file-word-o", "text-primary"],
    xls: ["fa-file-excel-o", "text-success"],
    xlsx: ["fa-file-excel-o", "text-success"],
    csv: ["fa-file-excel-o", "text-success"],
    ppt: ["fa-file-powerpoint-o", "text-warning"],
    pptx: ["fa-file-powerpoint-o", "text-warning"],
    png: ["fa-file-image-o", "text-info"],
    jpg: ["fa-file-image-o", "text-info"],
    jpeg: ["fa-file-image-o", "text-info"],
    gif: ["fa-file-image-o", "text-info"],
    webp: ["fa-file-image-o", "text-info"],
    svg: ["fa-file-image-o", "text-info"],
    bmp: ["fa-file-image-o", "text-info"],
    zip: ["fa-file-archive-o", "text-muted"],
    rar: ["fa-file-archive-o", "text-muted"],
    "7z": ["fa-file-archive-o", "text-muted"],
    mp4: ["fa-file-video-o", "text-primary"],
    mov: ["fa-file-video-o", "text-primary"],
    avi: ["fa-file-video-o", "text-primary"],
    mp3: ["fa-file-audio-o", "text-primary"],
    wav: ["fa-file-audio-o", "text-primary"],
    txt: ["fa-file-text-o", "text-secondary"],
    md: ["fa-file-text-o", "text-secondary"],
};

const ext = (name) => (name.includes(".") ? name.split(".").pop().toLowerCase() : "");

export class CloudDriveManager extends Component {
    static template = "cloud_drive_s3.CloudDriveManager";
    static props = { ...standardActionServiceProps };

    setup() {
        this.action = useService("action");
        this.notification = useService("notification");
        this.fileInput = useRef("fileInput");
        this._extDepth = 0;
        this._dragItem = null;
        this.state = useState({
            path: "",
            folders: [],
            files: [],
            loading: true,
            uploading: false,
            extDragging: false,
            dropTarget: null,
            isAdmin: false,
            canUpload: false,
            view: "grid",
            typeFilter: "all",
            sort: "name",
            search: "",
            ctx: { open: false, x: 0, y: 0, kind: null, item: null },
            clipboard: null,
            info: null,
            dialog: null,
            preview: null,
            share: null,
        });
        this.dialogInput = useRef("dialogInput");
        useExternalListener(window, "click", () => this.closeCtx());
        useExternalListener(window, "keydown", (ev) => {
            if (ev.key !== "Escape") {
                return;
            }
            if (this.state.dialog) {
                this.dialogCancel();
            } else if (this.state.share) {
                this.state.share = null;
            } else if (this.state.preview) {
                this.state.preview = null;
            } else {
                this.closeCtx();
                this.state.info = null;
            }
        });
        useEffect(
            () => {
                const input = this.dialogInput.el;
                if (
                    this.state.dialog?.mode === "prompt" &&
                    input instanceof HTMLInputElement
                ) {
                    input.focus();
                    input.select();
                }
            },
            () => [this.state.dialog],
        );
        onWillStart(async () => {
            this.state.isAdmin = await user.hasGroup(
                "cloud_drive_s3.group_drive_admin",
            );
            await this.load("");
        });
    }

    async load(path) {
        this.state.loading = true;
        this.closeCtx();
        try {
            const res = await rpc("/cloud_drive_s3/list", { path });
            this.state.path = path;
            this.state.folders = res.folders || [];
            this.state.files = res.files || [];
            this.state.canUpload = res.can_write_here || false;
        } finally {
            this.state.loading = false;
        }
    }

    get _query() {
        return this.state.search.trim().toLowerCase();
    }

    get shownFolders() {
        if (!["all", "folder"].includes(this.state.typeFilter)) {
            return [];
        }
        const q = this._query;
        return [...this.state.folders]
            .filter((f) => !q || f.name.toLowerCase().includes(q))
            .sort((a, b) => a.name.localeCompare(b.name));
    }

    get shownFiles() {
        const t = this.state.typeFilter;
        const q = this._query;
        let files = this.state.files.filter((f) => {
            if (q && !f.name.toLowerCase().includes(q)) return false;
            if (t === "all") return true;
            if (t === "folder") return false;
            if (t === "image") return f.is_image;
            if (t === "document") return DOC_EXTS.has(ext(f.name));
            if (t === "other") return !f.is_image && !DOC_EXTS.has(ext(f.name));
            return true;
        });
        const s = this.state.sort;
        files.sort((a, b) => {
            if (s === "size") return b.size - a.size;
            if (s === "date") return b.last_modified.localeCompare(a.last_modified);
            return a.name.localeCompare(b.name);
        });
        return files;
    }

    get isEmpty() {
        return !this.shownFolders.length && !this.shownFiles.length;
    }

    get breadcrumbs() {
        const crumbs = [{ name: "", path: "", home: true }];
        let acc = "";
        for (const part of this.state.path ? this.state.path.split("/") : []) {
            acc = acc ? `${acc}/${part}` : part;
            crumbs.push({ name: part, path: acc, home: false });
        }
        return crumbs;
    }

    formatSize(size) {
        return humanSize(size);
    }

    formatDate(iso) {
        return iso ? iso.replace("T", " ").slice(0, 19) : "";
    }

    fileIcon(name) {
        const [icon, cls] = FILE_ICONS[ext(name)] || ["fa-file-o", "text-secondary"];
        return { icon, cls };
    }

    _dirOf(key) {
        return key.includes("/") ? key.slice(0, key.lastIndexOf("/")) : "";
    }

    _join(dir, name) {
        return dir ? `${dir}/${name}` : name;
    }

    setView(view) {
        this.state.view = view;
    }

    clearSearch() {
        this.state.search = "";
    }

    async onDownload(file) {
        const res = await rpc("/cloud_drive_s3/presign_download", { key: file.key });
        window.open(res.url, "_blank", "noopener");
    }

    async onOpen(file) {
        const previewable = file.is_image || ext(file.name) === "pdf";
        if (!previewable) {
            await this.onDownload(file);
            return;
        }
        const res = await rpc("/cloud_drive_s3/presign_download", { key: file.key });
        this.state.preview = {
            name: file.name,
            url: res.url,
            kind: file.is_image ? "image" : "pdf",
            file,
        };
    }

    closePreview() {
        this.state.preview = null;
    }

    onUploadClick() {
        this.fileInput.el.click();
    }

    async onFilesSelected(ev) {
        const files = [...ev.target.files];
        ev.target.value = "";
        await this._uploadMany(files);
    }

    async _uploadMany(files) {
        if (!files.length) {
            return;
        }
        this.state.uploading = true;
        let done = 0;
        try {
            for (const file of files) {
                if (await this._uploadOne(file)) {
                    done++;
                }
            }
        } finally {
            this.state.uploading = false;
            await this.load(this.state.path);
        }
        if (done) {
            this.notification.add(
                done === 1 ? "File uploaded" : `${done} files uploaded`,
                { type: "success" },
            );
        }
    }

    async _uploadOne(file) {
        const key = this._join(this.state.path, file.name);
        const contentType = file.type || "application/octet-stream";
        const res = await rpc("/cloud_drive_s3/presign_upload", {
            key,
            content_type: contentType,
            size: file.size,
        });
        if (res.error === "too_large") {
            this.notification.add(
                `"${file.name}" exceeds the ${this.formatSize(res.limit)} limit.`,
                { type: "danger" },
            );
            return false;
        }
        const form = new FormData();
        for (const [name, value] of Object.entries(res.fields || {})) {
            form.append(name, value);
        }
        form.append("file", file);
        try {
            const put = await fetch(res.url, { method: "POST", body: form });
            if (!put.ok) {
                this.notification.add(`Upload failed for "${file.name}".`, {
                    type: "danger",
                });
                return false;
            }
            return true;
        } catch {
            this.notification.add(
                `Could not confirm upload of "${file.name}". If it is missing, ` +
                    `the bucket CORS may not allow this origin.`,
                { type: "warning" },
            );
            return false;
        }
    }

    async onNewFolder() {
        const name = await this._prompt("New folder", "", "Folder name");
        if (!name) {
            return;
        }
        await rpc("/cloud_drive_s3/mkdir", { path: this.state.path, name });
        await this.load(this.state.path);
    }

    async onDeleteFile(file) {
        const ok = await this._confirm(
            "Delete file",
            `Permanently delete "${file.name}"? This removes it from the Cloud drive.`,
            { danger: true, confirmLabel: "Delete" },
        );
        if (!ok) {
            return;
        }
        await rpc("/cloud_drive_s3/delete", { key: file.key });
        await this.load(this.state.path);
        this.notification.add(`"${file.name}" deleted`, { type: "success" });
    }

    async onDeleteFolder(folder) {
        const ok = await this._confirm(
            "Delete folder",
            `Permanently delete folder "${folder.name}"? It must be empty. This removes it from the Cloud drive.`,
            { danger: true, confirmLabel: "Delete" },
        );
        if (!ok) {
            return;
        }
        await rpc("/cloud_drive_s3/delete", { folder: folder.path });
        await this.load(this.state.path);
        this.notification.add(`Folder "${folder.name}" deleted`, { type: "success" });
    }

    async onRename(file) {
        const newName = await this._prompt("Rename", file.name, "New name");
        if (!newName || newName === file.name) {
            return;
        }
        const dst = this._join(this._dirOf(file.key), newName);
        await rpc("/cloud_drive_s3/move", { src: file.key, dst });
        await this.load(this.state.path);
    }

    async onDuplicate(file) {
        const dot = file.name.lastIndexOf(".");
        const copyName =
            dot > 0
                ? `${file.name.slice(0, dot)} (copy)${file.name.slice(dot)}`
                : `${file.name} (copy)`;
        const dst = this._join(this._dirOf(file.key), copyName);
        await rpc("/cloud_drive_s3/copy", { src: file.key, dst });
        await this.load(this.state.path);
    }

    async onRenameFolder(folder) {
        const newName = await this._prompt("Rename folder", folder.name, "New name");
        if (!newName || newName === folder.name) {
            return;
        }
        const dst = this._join(this._dirOf(folder.path), newName);
        await rpc("/cloud_drive_s3/move_folder", { src: folder.path, dst });
        await this.load(this.state.path);
    }

    async onDuplicateFolder(folder) {
        const dst = this._join(this._dirOf(folder.path), `${folder.name} (copy)`);
        await rpc("/cloud_drive_s3/copy_folder", { src: folder.path, dst });
        await this.load(this.state.path);
    }

    _isFolderInto(srcPath, destParent) {
        return destParent === srcPath || destParent.startsWith(`${srcPath}/`);
    }

    async onThumbError(ev, file) {
        const img = ev.target;
        if (img.dataset.refreshed) {
            return;
        }
        img.dataset.refreshed = "1";
        try {
            const res = await rpc("/cloud_drive_s3/presign_download", {
                key: file.key,
            });
            img.src = res.url;
        } catch {
            // A thumbnail whose presigned URL expired stays broken; the refresh
            // is best-effort and must not raise a notification over a preview.
        }
    }

    async onInfo(file) {
        const meta = await rpc("/cloud_drive_s3/info", { key: file.key });
        this.state.info = { name: file.name, ...meta };
    }

    closeInfo() {
        this.state.info = null;
    }

    async onShare(item, kind) {
        this.closeCtx();
        const path = kind === "folder" ? item.path : item.key;
        this.state.share = {
            path,
            name: item.name,
            kind,
            grants: [],
            query: "",
            results: [],
            level: "read",
            loading: true,
        };
        await this._shareReload();
    }

    async _shareReload() {
        const res = await rpc("/cloud_drive_s3/share/list", {
            path: this.state.share.path,
        });
        this.state.share.grants = res.grants || [];
        this.state.share.loading = false;
    }

    async onShareSearch(ev) {
        const q = ev.target.value;
        this.state.share.query = q;
        if (!q.trim()) {
            this.state.share.results = [];
            return;
        }
        const res = await rpc("/cloud_drive_s3/share/users", { query: q });
        const have = new Set(this.state.share.grants.map((g) => g.user_id));
        this.state.share.results = (res.users || []).filter((u) => !have.has(u.id));
    }

    async onShareAdd(userRec) {
        await rpc("/cloud_drive_s3/share/set", {
            path: this.state.share.path,
            user_id: userRec.id,
            access_level: this.state.share.level,
        });
        this.state.share.query = "";
        this.state.share.results = [];
        await this._shareReload();
    }

    async onShareLevel(grant, ev) {
        await rpc("/cloud_drive_s3/share/set", {
            path: this.state.share.path,
            user_id: grant.user_id,
            access_level: ev.target.value,
        });
        await this._shareReload();
    }

    async onShareRemove(grant) {
        await rpc("/cloud_drive_s3/share/unset", {
            path: this.state.share.path,
            user_id: grant.user_id,
        });
        await this._shareReload();
    }

    shareClose() {
        this.state.share = null;
    }

    _ask(config) {
        return new Promise((resolve) => {
            this.state.dialog = { ...config, resolve };
        });
    }

    _prompt(title, value = "", placeholder = "") {
        return this._ask({ mode: "prompt", title, value, placeholder });
    }

    _confirm(title, message, { danger = false, confirmLabel = "OK" } = {}) {
        return this._ask({ mode: "confirm", title, message, danger, confirmLabel });
    }

    dialogOk() {
        const d = this.state.dialog;
        this.state.dialog = null;
        d.resolve(d.mode === "prompt" ? (d.value || "").trim() || null : true);
    }

    dialogCancel() {
        const d = this.state.dialog;
        this.state.dialog = null;
        d.resolve(d.mode === "prompt" ? null : false);
    }

    onDialogKey(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.dialogOk();
        }
    }

    openConfiguration() {
        this.action.doAction("cloud_drive_s3.action_cloud_drive_config");
    }

    openAccess() {
        this.action.doAction("cloud_drive_s3.action_cloud_drive_access");
    }

    openMenu(ev, kind, item) {
        ev.preventDefault();
        this.state.ctx = {
            open: true,
            x: Math.min(ev.clientX, window.innerWidth - CTX_MENU_W),
            y: Math.min(ev.clientY, window.innerHeight - CTX_MENU_H),
            kind,
            item,
        };
    }

    closeCtx() {
        if (this.state.ctx.open) {
            this.state.ctx = { ...this.state.ctx, open: false };
        }
    }

    onCut(item, kind = "file") {
        this.state.clipboard =
            kind === "folder"
                ? { name: item.name, path: item.path, kind: "folder" }
                : { name: item.name, key: item.key, kind: "file" };
    }

    cancelClipboard() {
        this.state.clipboard = null;
    }

    async pasteHere() {
        const cb = this.state.clipboard;
        if (!cb) {
            return;
        }
        if (cb.kind === "folder") {
            if (this._isFolderInto(cb.path, this.state.path)) {
                this.notification.add("Cannot move a folder into itself.", {
                    type: "warning",
                });
                return;
            }
            const dst = this._join(this.state.path, cb.name);
            if (dst !== cb.path) {
                await rpc("/cloud_drive_s3/move_folder", { src: cb.path, dst });
            }
        } else {
            const dst = this._join(this.state.path, cb.name);
            if (dst !== cb.key) {
                await rpc("/cloud_drive_s3/move", { src: cb.key, dst });
            }
        }
        this.state.clipboard = null;
        await this.load(this.state.path);
    }

    onItemDragStart(ev, item, kind = "file") {
        this._dragItem = { kind, item };
        ev.dataTransfer.effectAllowed = "move";
    }

    onItemDragEnd() {
        this._dragItem = null;
        this.state.dropTarget = null;
    }

    onFolderDragOver(folder) {
        const drag = this._dragItem;
        if (!drag) {
            return;
        }
        if (drag.kind === "folder" && this._isFolderInto(drag.item.path, folder.path)) {
            return;
        }
        this.state.dropTarget = folder.path;
    }

    onFolderDragLeave(folder) {
        if (this.state.dropTarget === folder.path) {
            this.state.dropTarget = null;
        }
    }

    async _moveInto(destPath, file) {
        const dst = this._join(destPath, file.name);
        if (dst !== file.key) {
            await rpc("/cloud_drive_s3/move", { src: file.key, dst });
            await this.load(this.state.path);
        }
    }

    async _moveFolderInto(destParent, folder) {
        if (this._isFolderInto(folder.path, destParent)) {
            return;
        }
        const dst = this._join(destParent, folder.name);
        if (dst !== folder.path) {
            await rpc("/cloud_drive_s3/move_folder", { src: folder.path, dst });
            await this.load(this.state.path);
        }
    }

    async onItemDrop(target) {
        const drag = this._dragItem;
        this._dragItem = null;
        this.state.dropTarget = null;
        if (!drag) {
            return;
        }
        if (drag.kind === "folder") {
            await this._moveFolderInto(target.path, drag.item);
        } else {
            await this._moveInto(target.path, drag.item);
        }
    }

    onExtDragEnter() {
        if (!this.state.canUpload || this._dragItem) {
            return;
        }
        this._extDepth++;
        this.state.extDragging = true;
    }

    onExtDragOver() {}

    onExtDragLeave() {
        if (!this.state.canUpload || this._dragItem) {
            return;
        }
        this._extDepth = Math.max(0, this._extDepth - 1);
        if (this._extDepth === 0) {
            this.state.extDragging = false;
        }
    }

    async onExtDrop(ev) {
        this._extDepth = 0;
        this.state.extDragging = false;
        if (!this.state.canUpload || this._dragItem) {
            return;
        }
        await this._uploadMany([...(ev.dataTransfer?.files || [])]);
    }
}

registry.category("actions").add("cloud_drive_s3_manager", CloudDriveManager);
