export const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string,
  ) {
    super(message);
  }
}

async function check(res: Response): Promise<Response> {
  if (res.ok) return res;
  const body = await res.json().catch(() => null);
  throw new ApiError(body?.detail ?? `Request failed: ${res.status}`, res.status, body?.code);
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await check(await fetch(`${BASE_URL}${path}`));
  return res.json() as Promise<T>;
}

export async function apiSend<T>(method: "POST" | "DELETE", path: string, body?: unknown): Promise<T> {
  const res = await check(
    await fetch(`${BASE_URL}${path}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  );
  return (res.status === 204 ? undefined : res.json()) as Promise<T>;
}

/** POST, then call onEvent for each server-sent event until the stream ends. */
export async function apiStream(
  path: string,
  body: unknown,
  onEvent: (event: string, data: any) => void,
  signal: AbortSignal,
): Promise<void> {
  const res = await check(
    await fetch(`${BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
      signal,
    }),
  );
  const reader = res.body!.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += value;
    let end: number;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      const event = /^event: (.*)$/m.exec(block)?.[1];
      const data = /^data: (.*)$/m.exec(block)?.[1];
      if (event && data) onEvent(event, JSON.parse(data));
    }
  }
}
