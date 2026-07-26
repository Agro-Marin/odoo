import { registry } from "@web/core/registry";
import { contains } from "@web/../tests/utils";

// The fixture holds 31 messages: 30 created by ``test_load_more`` plus the one
// ``TestUIPortal.setUp`` posts. The first page is ``Store.FETCH_LIMIT`` (30),
// and ``Thread.loadOlder`` is set from ``fetched.length === FETCH_LIMIT``, so a
// full first page necessarily offers "Load More". Asserting 30 rendered AND no
// "Load More" (as this tour first did) is therefore self-contradictory -- it
// can only hold for a short first page, which would render fewer than 30.
// Walking the whole load-more flow keeps the regression this tour was written
// for (``showLoadOlder`` used to crash on portal, where ``messageHighlight`` is
// undefined -- the getter is evaluated to render the button either way) and
// additionally covers the button correctly disappearing once the last, short
// page has been fetched.
registry.category("web_tour.tours").add("load_more_tour", {
    steps: () => [
        {
            trigger: "#chatterRoot:shadow .o-mail-Thread .o-mail-Message",
            run: async function () {
                await contains(".o-mail-Thread .o-mail-Message", {
                    count: 30,
                    target: document.querySelector("#chatterRoot").shadowRoot,
                });
            },
        },
        {
            // a full first page => there may be older messages => button shown
            trigger: "#chatterRoot:shadow .o-mail-Thread button:contains(Load More)",
            run: "click",
        },
        {
            trigger: "#chatterRoot:shadow .o-mail-Thread .o-mail-Message",
            run: async function () {
                await contains(".o-mail-Thread .o-mail-Message", {
                    count: 31,
                    target: document.querySelector("#chatterRoot").shadowRoot,
                });
            },
        },
        {
            // The second page was short (1 message), so fetchMoreMessages
            // clears loadOlder and the button is dropped from the DOM by its
            // `t-if="showLoadOlder"`. Assert its ABSENCE: a `:not(:visible)`
            // trigger can never match here, because a removed element matches
            // no selector at all (and the button's only invisible state,
            // `opacity-0` while unmounted, still counts as visible).
            trigger:
                "#chatterRoot:shadow .o-mail-Thread:not(:has(button:contains(Load More)))",
        },
    ],
});
