import { defineMailModels, mockGetMedia } from "@mail/../tests/mail_test_helpers";
import { LocalMediaController } from "@mail/discuss/call/common/local_media_controller";
import { describe, expect, test } from "@odoo/hoot";
import { advanceTime } from "@odoo/hoot-mock";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";

describe.current.tags("desktop");
defineMailModels();

/**
 * Headless LocalMediaController harness: plain shared state, a fake local
 * session and recording hooks.
 */
function makeController() {
    const state = {
        channel: { id: 1 },
        micAudioTrack: undefined,
        screenAudioTrack: undefined,
        audioTrack: undefined,
        cameraTrack: undefined,
        screenTrack: undefined,
        disconnectAudioMonitor: undefined,
        sourceCameraStream: null,
        sourceScreenStream: null,
        sendCamera: false,
        sendScreen: false,
    };
    const session = { isMute: false, isTalking: false };
    const settings = {
        audioConstraints: true,
        cameraConstraints: true,
        useBlur: false,
        use_push_to_talk: true, // keeps linkVoiceActivation away from monitorAudio
        voiceActivationThreshold: 0.05,
        cameraFacingMode: undefined,
        setUseBlur: () => {},
    };
    const steps = {
        setMute: [],
        uploads: [],
        unavailable: [],
        sounds: [],
        toggles: [],
    };
    const controller = new LocalMediaController({
        state,
        hooks: {
            getSettings: () => settings,
            getLocalSession: () => session,
            getSelfSession: () => session,
            updateTrackUpload: async (type, track) => {
                steps.uploads.push([type, track]);
            },
            setMute: async (isMute) => {
                steps.setMute.push(isMute);
                session.isMute = isMute;
            },
            onMediaUnavailable: (media) => steps.unavailable.push(media),
            toggleVideo: async (type, options) => steps.toggles.push([type, options]),
            playSound: (soundName) => steps.sounds.push(soundName),
            notify: () => {},
            setTalking: () => {},
            refreshMicAudioStatus: async () => {},
        },
    });
    return { controller, state, session, settings, steps };
}

test("resetMicAudioTrack acquires the mic and applies the session mute state", async () => {
    mockGetMedia();
    const { controller, state, session, steps } = makeController();
    await controller.resetMicAudioTrack({ force: true });
    expect(state.micAudioTrack).not.toBe(undefined);
    expect(state.micAudioTrack.kind).toBe("audio");
    // single audio source: no mixing, the mic track is uploaded directly
    expect(state.audioTrack).toBe(state.micAudioTrack);
    expect(controller.audioContext).toBe(undefined);
    // preemptive mute while acquiring, then unmute on success
    expect(steps.setMute).toEqual([true, false]);
    expect(steps.uploads.at(-1)).toEqual(["audio", state.micAudioTrack]);
    // mute/deaf/talk state application on the track
    expect(state.micAudioTrack.enabled).toBe(false); // not talking yet
    session.isTalking = true;
    controller.applyMicState();
    expect(state.micAudioTrack.enabled).toBe(true);
    session.isMute = true;
    controller.applyMicState();
    expect(state.micAudioTrack.enabled).toBe(false);
});

test("mic + screen audio are mixed, and the mix is torn down with the screen audio", async () => {
    mockGetMedia();
    const { controller, state } = makeController();
    await controller.resetMicAudioTrack({ force: true });
    const micTrack = state.micAudioTrack;
    const screenStream = await browser.navigator.mediaDevices.getUserMedia({
        audio: true,
    });
    state.screenAudioTrack = screenStream.getAudioTracks()[0];
    await controller.updateAudioTrack();
    // both sources: a mixed destination track is produced
    expect(controller.audioContext).not.toBe(undefined);
    const mixedTrack = state.audioTrack;
    expect(mixedTrack).not.toBe(micTrack);
    expect(mixedTrack).not.toBe(state.screenAudioTrack);
    // screen audio goes away: the mix AudioContext is torn down and the
    // now-unused mixed track is stopped
    state.screenAudioTrack.stop();
    state.screenAudioTrack = undefined;
    await controller.updateAudioTrack();
    expect(controller.audioContext).toBe(undefined);
    expect(state.audioTrack).toBe(micTrack);
    expect(mixedTrack.readyState).toBe("ended");
});

test("mic track 'ended' resets the track and mutes the session", async () => {
    mockGetMedia();
    const { controller, state, steps } = makeController();
    await controller.resetMicAudioTrack({ force: true });
    const micTrack = state.micAudioTrack;
    steps.setMute.length = 0;
    // e.g. the user retracts the microphone permission
    micTrack.dispatchEvent(new Event("ended"));
    await advanceTime(10);
    expect(state.micAudioTrack).toBe(undefined);
    expect(state.audioTrack).toBe(undefined);
    // muted by the inner reset, then explicitly by the ended handler
    expect(steps.setMute).toEqual([true, true]);
    // the senders were resynchronized without a track
    expect(steps.uploads.at(-1)).toEqual(["audio", undefined]);
});

test("getUserMedia failure warns and still resynchronizes the senders", async () => {
    patchWithCleanup(browser.navigator.mediaDevices, {
        getUserMedia() {
            throw new Error("permission denied");
        },
    });
    const { controller, state, steps } = makeController();
    await controller.resetMicAudioTrack({ force: true });
    expect(state.micAudioTrack).toBe(undefined);
    expect(steps.unavailable).toEqual([{ microphone: true }]);
    // the outgoing audio is still rebuilt (an ended track must not linger)
    expect(steps.uploads.at(-1)).toEqual(["audio", undefined]);
});

test("setVideo owns the camera and screen track lifecycle", async () => {
    mockGetMedia();
    const { controller, state, steps } = makeController();
    await controller.setVideo(undefined, "camera", { activateVideo: true });
    const cameraTrack = state.cameraTrack;
    expect(cameraTrack.kind).toBe("video");
    expect(state.sendCamera).toBe(true);
    expect(state.sourceCameraStream).not.toBe(null);
    await controller.setVideo(undefined, "screen", { activateVideo: true });
    expect(state.screenTrack.kind).toBe("video");
    expect(state.sendScreen).toBe(true);
    expect(steps.sounds).toEqual(["screen-sharing"]);
    // the "ended" listener funnels into the coordinator's toggleVideo
    state.cameraTrack.dispatchEvent(new Event("ended"));
    await advanceTime(10);
    expect(steps.toggles).toEqual([["camera", { force: false }]]);
    // deactivation stops the tracks and closes the source streams
    await controller.setVideo(state.cameraTrack, "camera", {
        activateVideo: false,
    });
    expect(cameraTrack.readyState).toBe("ended");
    expect(state.cameraTrack).toBe(undefined);
    expect(state.sourceCameraStream).toBe(null);
});

test("dispose stops every owned track and resets the shared slots", async () => {
    mockGetMedia();
    const { controller, state } = makeController();
    await controller.resetMicAudioTrack({ force: true });
    await controller.setVideo(undefined, "camera", { activateVideo: true });
    const micTrack = state.micAudioTrack;
    const cameraTrack = state.cameraTrack;
    controller.dispose();
    expect(micTrack.readyState).toBe("ended");
    expect(cameraTrack.readyState).toBe("ended");
    expect(state.micAudioTrack).toBe(undefined);
    expect(state.audioTrack).toBe(undefined);
    expect(state.cameraTrack).toBe(undefined);
    expect(state.screenTrack).toBe(undefined);
    expect(state.sourceCameraStream).toBe(null);
    expect(state.sourceScreenStream).toBe(null);
    expect(state.sendCamera).toBe(false);
    expect(state.sendScreen).toBe(false);
    expect(controller.audioContext).toBe(undefined);
});
