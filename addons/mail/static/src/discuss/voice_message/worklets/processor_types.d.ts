/** Browser-provided globals in the AudioWorklet execution context. */
interface AudioWorkletProcessor {
    readonly port: MessagePort;
}
declare var AudioWorkletProcessor: {
    new (options?: AudioWorkletNodeOptions): AudioWorkletProcessor;
};
declare function registerProcessor<Options>(
    name: string,
    processor: new (options: Options) => AudioWorkletProcessor & {
        process(
            inputs: Float32Array[][],
            outputs: Float32Array[][],
            parameters: Record<string, Float32Array>,
        ): boolean;
    },
): void;
