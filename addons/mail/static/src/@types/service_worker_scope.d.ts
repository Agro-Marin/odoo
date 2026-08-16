export {};

declare global {
    const idbKeyval: {
        Store: new (dbName: string, storeName: string) => object;
        set: (key: string, value: any, store?: object) => Promise<void>;
        get: (key: string, store?: object) => Promise<any>;
    };

    const PUSH_NOTIFICATION_TYPE: typeof import("@mail/service_worker_utils").PUSH_NOTIFICATION_TYPE;
    const PUSH_NOTIFICATION_ACTION: typeof import("@mail/service_worker_utils").PUSH_NOTIFICATION_ACTION;
    const arrayBufferToBase64Url: typeof import("@mail/service_worker_utils").arrayBufferToBase64Url;
    const planPushNotification: typeof import("@mail/service_worker_utils").planPushNotification;
    const notificationTargetPath: typeof import("@mail/service_worker_utils").notificationTargetPath;

    interface ServiceWorkerGlobalScope {
        handlePushEventMessageFns: Map<string, () => void>;
    }
}
