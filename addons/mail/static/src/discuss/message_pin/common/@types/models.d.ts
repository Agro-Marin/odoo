declare module "models" {
    export interface Message {
        pin: () => Deferred<boolean>;
        pinned_at: import("luxon").DateTime;
        threadAsPinned: Thread;
        unpin: () => Deferred<boolean>;
    }
    export interface Thread {
        fetchPinnedMessages: () => Promise<void>;
        has_pinned_messages: boolean | undefined;
        pinnedMessages: Message[];
        pinnedMessagesState: "loaded" | "loading" | "error" | undefined;
        setMessagePin: (message: Message, pinned: boolean) => Promise<void>;
    }
}
