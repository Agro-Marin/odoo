import "services";

declare module "services" {
    interface ModifierTestService {
        _silent: boolean;
        readonly silent: ModifierTestService;
        asyncMethod(): Promise<boolean>;
    }

    interface Services {
        failing_service: { start(): { boom(): Promise<never> } };
        live_failing_service: { start(): { boom(): Promise<never> } };
        modifier_service: { start(): ModifierTestService };
        custom_notification: {
            start(): Omit<ReturnType<typeof import("@web/ui/notification/notification_service").notificationService.start>, "add"> & {
                add(message: string, options: import("@web/ui/notification/notification_service").NotificationOptions & {flavour: string}): () => void;
            };
        };
    }
}
