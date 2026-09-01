import "@website_mail/interactions/follow";

import { describe, expect, test } from "@odoo/hoot";
import { onRpc } from "@web/../tests/web_test_helpers";
import {
    setupInteractionWhiteList,
    startInteractions,
} from "@web/../tests/public/helpers";

setupInteractionWhiteList("website_mail.follow");
describe.current.tags("interaction_dev");

const template = `
    <div class="input-group js_follow" data-id="4" data-object="res.partner" data-follow="off">
        <input type="email" name="email" class="js_follow_email form-control" />
        <button class="btn js_unfollow_btn">Unsubscribe</button>
        <button class="btn js_follow_btn">Subscribe</button>
    </div>
    <div class="input-group js_follow" data-id="7" data-object="res.partner" data-follow="off">
        <input type="email" name="email" class="js_follow_email form-control" />
        <button class="btn js_unfollow_btn">Unsubscribe</button>
        <button class="btn js_follow_btn">Subscribe</button>
    </div>
`;

test("each widget reads its own record's follow state on initial render", async () => {
    onRpc("/website_mail/is_follower", () => [
        { is_user: false, email: "" },
        { "res.partner": [4] },
    ]);
    await startInteractions(template);
    expect('.js_follow[data-id="4"]').toHaveAttribute("data-follow", "on");
    expect('.js_follow[data-id="7"]').toHaveAttribute("data-follow", "off");
});
