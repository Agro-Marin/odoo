import {
    click,
    contains,
    defineMailModels,
    mockGetMedia,
    openDiscuss,
    patchVoiceMessageAudio,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";
import { Mp3Encoder } from "@mail/discuss/voice_message/common/mp3_encoder";
import { loadLamejs } from "@mail/discuss/voice_message/common/voice_message_service";
import { VoicePlayer } from "@mail/discuss/voice_message/common/voice_player";
import { patchable } from "@mail/discuss/voice_message/common/voice_recorder";
import { describe, expect, globals, test } from "@odoo/hoot";
import { Deferred, mockDate } from "@odoo/hoot-mock";
import {
    Command,
    getService,
    patchWithCleanup,
    serverState,
} from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineMailModels();

test("make voice message in chat", async () => {
    const file = new File([new Uint8Array(25000)], "test.mp3", { type: "audio/mp3" });
    const voicePlayerDrawing = new Deferred();
    patchWithCleanup(Mp3Encoder.prototype, {
        encode() {},
        finish() {
            return Array(500).map(() => new Int8Array());
        },
    });
    patchWithCleanup(patchable, { makeFile: () => file });
    patchWithCleanup(VoicePlayer.prototype, {
        async drawWave(...args) {
            const res = await super.drawWave(...args);
            voicePlayerDrawing.resolve();
            return res;
        },
        async fetchFile() {
            return super.fetchFile("/mail/static/src/audio/call-invitation.mp3");
        },
        _fetch(url) {
            if (url.includes("call-invitation.mp3")) {
                const realFetch = globals.fetch;
                return realFetch(...arguments);
            }
            return super._fetch(...arguments);
        },
    });
    mockGetMedia();
    const resources = patchVoiceMessageAudio();
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "Demo" });
    const channelId = pyEnv["discuss.channel"].create({
        channel_member_ids: [
            Command.create({ partner_id: serverState.partnerId }),
            Command.create({ partner_id: partnerId }),
        ],
        channel_type: "chat",
    });
    await start();
    await openDiscuss(channelId);
    await loadLamejs();
    await click(".o-mail-Composer button[title='More Actions']");
    await contains(".dropdown-item:contains('Voice Message')");
    mockDate("2023-07-31 13:00:00");
    await click(".dropdown-item:contains('Voice Message')");
    await contains(".o-mail-VoiceRecorder", { text: "00 : 00" });
    mockDate("2023-07-31 13:00:10.500");
    resources.audioProcessor.process([[new Float32Array(128)]]);
    await contains(".o-mail-VoiceRecorder", { text: "00 : 10" });
    await click(".o-mail-Composer button[title='Stop Recording']");
    await contains(".o-mail-VoicePlayer");
    await voicePlayerDrawing;
    await contains(".o-mail-VoicePlayer button[title='Play']");
    await contains(".o-mail-VoicePlayer canvas", { count: 2 });
    await contains(".o-mail-VoicePlayer", { text: "00 : 03" });
    await click(".o-mail-Composer button[title='More Actions']");
    await contains(".dropdown-item:contains('Attach Files')");
    await contains(".dropdown-item:contains('Voice Message')", { count: 0 });
});

test("deleting a non-playing voice message keeps cross-player exclusivity", async () => {
    await startServer();
    await start();
    const store = getService("mail.store");
    const voiceService = getService("discuss.voice_message");
    const metaA = store["discuss.voice.metadata"].insert({ id: 1 });
    const metaB = store["discuss.voice.metadata"].insert({ id: 2 });
    const attachmentA = store["ir.attachment"].insert({ id: 10, voice_ids: [metaA] });
    const attachmentB = store["ir.attachment"].insert({ id: 11, voice_ids: [metaB] });
    voiceService.activePlayer = { props: { attachment: attachmentA } };
    attachmentB.delete();
    expect(voiceService.activePlayer).not.toBe(null);
    expect(voiceService.activePlayer.props.attachment.eq(attachmentA)).toBe(true);
    attachmentA.delete();
    expect(voiceService.activePlayer).toBe(null);
});
