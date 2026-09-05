/** @odoo-module native */
import { loader } from "@web/components/emoji_picker";
import { patch } from "@web/core/utils/patch";
import { url } from "@web/core/utils/urls";
import { session } from "@web/session";

patch(loader, {
    // The embed is a native-ESM build whose import map the loader installed on
    // the host page, so the emoji bundle is imported as a module from the same
    // server rather than injected as a classic script.
    loadEmoji: () =>
        import(
            /* @vite-ignore */
            url("/im_livechat/emoji_bundle", undefined, {
                origin: session.livechatData.serverUrl,
            })
        ),
});
