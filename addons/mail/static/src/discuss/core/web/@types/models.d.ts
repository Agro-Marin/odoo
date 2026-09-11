declare module "models" {
    export interface Thread {
        storeAsCounterChannel: Store;
    }
    export interface Store {
        counterChannels: Thread[];
        getSelfImportantChannels: () => Thread[];
        getSelfRecentChannels: () => Thread[];
        initChannelsUnreadCounter: number;
        onClickPartnerMention: (ev: MouseEvent, id: number) => void;
    }
}
