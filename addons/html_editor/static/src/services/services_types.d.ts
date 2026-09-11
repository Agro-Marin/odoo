declare module "services" {
    interface Services {
        upload: typeof import("@html_editor/main/media/media_dialog/upload_progress_toast/upload_service").uploadService;
        uploadLocalFiles: typeof import("@html_editor/services/upload_local_files_service").uploadLocalFileService;
    }
}
