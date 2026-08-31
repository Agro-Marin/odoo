import { mailModels } from "@mail/../tests/mail_test_helpers";
import { serverState } from "@web/../tests/web_test_helpers";

export class IrWebSocket extends mailModels.IrWebSocket {
    /**
     * @override
     * @type {typeof busModels.IrWebSocket["prototype"]["_get_bus_channels"]}
     */
    _get_bus_channels(channels) {
        channels = [...super._get_bus_channels(channels)];
        const result = channels;
        for (const channel of channels) {
            if (channel === "im_livechat.looking_for_help") {
                result.push([
                    this.env["res.groups"].browse(serverState.groupLivechatId)[0],
                    "LOOKING_FOR_HELP",
                ]);
            }
        }
        return result.filter((channel) => channel !== "im_livechat.looking_for_help");
    }
}
