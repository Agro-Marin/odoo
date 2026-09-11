import type { FileModelData } from "@web/components/file_viewer/file_model";

// The mixin reads these fields; attachment initialization data supplies them.
declare module "@mail/core/common/attachment_model" {
    interface Attachment extends FileModelData {
        name: string;
    }
}
