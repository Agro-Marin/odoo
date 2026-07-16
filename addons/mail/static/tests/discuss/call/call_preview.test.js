import { mockBlurManager } from "@mail/../tests/discuss/call/mock_blur_manager";
import {
    contains,
    defineMailModels,
    mockGetMedia,
    start,
} from "@mail/../tests/mail_test_helpers";
import { CallPreview } from "@mail/discuss/call/common/call_preview";
import { describe, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, useState, xml } from "@odoo/owl";
import { getService, mountWithCleanup } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineMailModels();

test("enabling the camera preview reports the camera state even before the video element mounts", async () => {
    mockGetMedia();
    await start();
    const settings = [];
    await mountWithCleanup(CallPreview, {
        props: {
            activateCamera: 1,
            onSettingsChanged: (s) => settings.push(s),
        },
    });
    // The <video> element only renders once the stream is set, so the camera is enabled before the
    // element exists. The parent must still be told the camera is on, otherwise a guest whose camera
    // is on in the preview joins the call with the camera off.
    await contains("video");
    expect(settings).toEqual([{ camera: true }]);
});

test("closing the preview tears down the blur manager and its stream", async () => {
    mockGetMedia();
    const managers = mockBlurManager();
    await start();
    // wrap in a parent so the preview can be unmounted mid-test (toggling the
    // `t-if` fires CallPreview's onWillDestroy)
    class Parent extends Component {
        static components = { CallPreview };
        static props = [];
        static template = xml`
            <CallPreview t-if="state.show" activateCamera="1" onSettingsChanged="() => {}"/>
        `;
        setup() {
            this.state = useState({ show: true });
        }
    }
    const parent = await mountWithCleanup(Parent);
    // camera stream is up, so enableBlur() won't early-return on a missing stream
    await contains("video");

    // enabling blur flips the (localStorage-backed) `useBlur` setting, whose
    // change fires CallPreview's onChange -> enableBlur -> (mocked)
    // applyBlurEffect -> MockBlurManager
    getService("mail.store").settings.setUseBlur(true);
    await animationFrame();
    expect(managers).toHaveLength(1);
    const manager = managers[0];
    expect(manager.closed).toBe(false);
    expect(manager.blurStream.getVideoTracks()[0].readyState).toBe("live");

    // unmount the preview -> onWillDestroy
    parent.state.show = false;
    await animationFrame();

    // regression: onWillDestroy previously closed only the audio/video streams,
    // leaking the BlurManager (worker + capture stream) and its output stream
    expect(manager.closed).toBe(true);
    expect(manager.blurStream.getVideoTracks()[0].readyState).toBe("ended");
});
