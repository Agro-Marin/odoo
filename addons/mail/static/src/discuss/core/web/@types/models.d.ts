declare module "models" {
    export interface Store {
        counterChannels: Thread[];
        getSelfImportantChannels: () => Thread[];
        getSelfRecentChannels: () => Thread[];
        initChannelsUnreadCounter: number;
        onClickPartnerMention: (ev: MouseEvent, id: number) => void;
    }
}
