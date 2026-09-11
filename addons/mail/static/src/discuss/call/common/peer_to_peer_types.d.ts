import type { Info, Peer } from "@mail/discuss/call/common/peer_to_peer";

export type PeerUpdate =
    | { name: "broadcast"; payload: { senderId: number; message: unknown } }
    | {
          name: "connection_change";
          payload: {
              id: number;
              peer: Peer;
              state: RTCPeerConnectionState | "searching for network";
          };
      }
    | { name: "disconnect"; payload: { sessionId: number } }
    | { name: "info_change"; payload: Record<number, Partial<Info>> }
    | { name: "recovery"; payload: { id: number } }
    | {
          name: "track";
          payload: {
              sessionId: number;
              type: "audio" | "camera" | "screen";
              track: MediaStreamTrack;
              active: boolean;
              sequence: number;
          };
      };

declare module "@mail/discuss/call/common/peer_to_peer" {
    interface PeerToPeer {
        addEventListener(
            type: "update",
            listener: (event: CustomEvent<PeerUpdate>) => void,
            options?: boolean | AddEventListenerOptions,
        ): void;
        addEventListener(
            type: string,
            listener: EventListenerOrEventListenerObject,
            options?: boolean | AddEventListenerOptions,
        ): void;
    }
}
