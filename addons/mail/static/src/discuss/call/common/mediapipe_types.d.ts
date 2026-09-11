export {};
declare global {
    interface Window {
        SelfieSegmentation: new (options: { locateFile(file: string): string }) => {
            setOptions(options: { selfieMode: boolean; modelSelection: number }): void;
            onResults(
                callback: (result: import("./blur_manager").SegmentationResult) => void,
            ): void;
            send(input: { image: HTMLVideoElement }): Promise<void>;
            close(): Promise<void>;
        };
    }
}
