import { registry } from "@web/core/registry";

registry
    .category("web_tour.tours")
    .add("discuss_go_back_to_thread_from_breadcrumbs.js", {
        steps: () => [
            { trigger: ".o-mail-DiscussContent-threadName[title='Inbox']" },
            {
                trigger: ".o-mail-DiscussSidebar-item:contains('Starred messages')",
                run: "click",
            },
            {
                // Wait for the new thread to be rendered before navigating away.
                // The action's display name (hence the breadcrumb the next
                // action captures) is pushed from a render effect on
                // `thread.displayName`, so opening another action in the same
                // frame snapshots the *previous* thread's name ("Inbox").
                content: "Wait for the starred mailbox to be displayed",
                trigger: ".o-mail-DiscussContent-threadName[title='Starred messages']",
            },
            {
                trigger: "button[title='View or join channels']:not(:visible)",
                run: "click",
            },
            { trigger: ".breadcrumb-item:contains('Starred messages')", run: "click" },
            { trigger: ".o-mail-DiscussContent-threadName[title='Starred messages']" },
        ],
    });
