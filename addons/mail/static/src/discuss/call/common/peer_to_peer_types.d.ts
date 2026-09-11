import "@mail/discuss/call/common/peer_to_peer";
declare module "@mail/discuss/call/common/peer_to_peer" {
    interface PeerToPeer {
        addEventListener(
            type: "update",
            listener: (event: CustomEvent<{ name: string; payload: any }>) => void,
            options?: boolean | AddEventListenerOptions,
        ): void;
        addEventListener(
            type: string,
            listener: EventListenerOrEventListenerObject,
            options?: boolean | AddEventListenerOptions,
        ): void;
    }
}
