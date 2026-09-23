import { expect, test } from "@odoo/hoot";
import { allowTranslations } from "@web/../tests/web_test_helpers";
import { renderToElement } from "@web/core/utils/render";

test("the review composer renders its stars from the context it is given", () => {
    allowTranslations();
    const composerEl = renderToElement("portal.Composer", {
        widget: {
            options: {
                allow_composer: true,
                display_composer: true,
                display_rating: true,
                default_rating_value: 4,
                send_button_label: "Post",
            },
        },
    });
    expect(composerEl.querySelectorAll(".o-mail-Composer-starCard")).toHaveCount(1);
    expect(
        composerEl.querySelectorAll(".o-mail-Composer-starCard .fa-star.fa-solid"),
    ).toHaveCount(4);
});
