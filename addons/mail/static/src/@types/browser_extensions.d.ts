interface Document {
    readonly webkitFullscreenElement?: Element | null;
    mozCancelFullScreen?: () => void | Promise<void>;
    webkitCancelFullScreen?: () => void | Promise<void>;
}
interface HTMLElement {
    mozRequestFullScreen?: () => void | Promise<void>;
    webkitRequestFullscreen?: () => void | Promise<void>;
}
interface Window {
    documentPictureInPicture?: {
        requestWindow(options?: { width?: number; height?: number }): Promise<Window>;
    };
}

interface Navigator {
    brave?: { isBrave(): Promise<boolean> };
}
interface MailKeyValueStore {
    readonly storeName: string;
    readonly _dbp: Promise<IDBDatabase>;
}
interface Window {
    idbKeyval?: {
        Store: new (dbName?: string, storeName?: string) => MailKeyValueStore;
        set(key: IDBValidKey, value: unknown, store?: MailKeyValueStore): Promise<void>;
    };
}

interface Window {
    chrome?: {
        runtime?: {
            sendMessage(
                extensionId: string,
                message: { type: string; value?: unknown },
            ): Promise<string>;
        };
    };
}
