/** Serialize explicit tab operations behind restoration of session-owned state. */
export class StartupGate {
  private releaseGate!: () => void;
  private error: string | null = null;
  private readonly ready = new Promise<void>((resolve) => {
    this.releaseGate = resolve;
  });

  async wait(): Promise<void> {
    await this.ready;
    if (this.error) {
      throw new Error(this.error);
    }
  }

  release(): void {
    this.releaseGate();
  }

  fail(message: string): void {
    this.error = message;
    this.releaseGate();
  }
}

export async function withStartupTimeout<T>(
  operation: Promise<T>,
  label: string,
  timeoutMs = 5_000,
): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      operation,
      new Promise<T>((_resolve, reject) => {
        timer = setTimeout(() => reject(new Error(`${label} timed out.`)), timeoutMs);
      }),
    ]);
  } finally {
    if (timer !== undefined) {
      clearTimeout(timer);
    }
  }
}
