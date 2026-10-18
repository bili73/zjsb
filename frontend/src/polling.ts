// Serial, cancelable reads. The callback decides whether another read is needed.
export class ReadLoop {
  private controller: AbortController | undefined
  private timer: ReturnType<typeof setTimeout> | undefined
  private generation = 0
  private readonly read: (signal: AbortSignal) => Promise<number | null>
  constructor(read: (signal: AbortSignal) => Promise<number | null>) { this.read = read }
  start(delayMs = 0) {
    this.stop()
    const generation = this.generation
    const run = async () => {
      const controller = new AbortController()
      this.controller = controller
      try {
        const delay = await this.read(controller.signal)
        if (generation === this.generation && !controller.signal.aborted && delay !== null) this.timer = setTimeout(run, delay)
      } catch (error) {
        if (!controller.signal.aborted) throw error
      }
    }
    if (delayMs > 0) this.timer = setTimeout(run, delayMs)
    else void run()
  }
  stop() { this.generation++; clearTimeout(this.timer); this.controller?.abort() }
}
