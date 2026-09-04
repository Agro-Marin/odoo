/** @odoo-module native */
import { patch } from "@web/core/utils/patch";

import { AttachmentList } from "@mail/core/common/attachment_list";

import { VoiceTranscript } from "./voice_transcript.js";

patch(AttachmentList, {
    components: { ...AttachmentList.components, VoiceTranscript },
});
