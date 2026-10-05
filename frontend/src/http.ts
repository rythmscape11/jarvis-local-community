/** Show a safe, readable API error instead of raw JSON or a proxy HTML page. */
export async function responseError(response: Response): Promise<Error> {
  const body = await response.text();
  try {
    const detail: unknown = JSON.parse(body).detail;
    if (typeof detail === "string" && detail.trim())
      return new Error(detail.slice(0, 500));
  } catch {
    // Plain text is supported; structured validation errors use the status.
    if (body.length <= 500 && !/[<>]/.test(body) && body.trim())
      return new Error(body);
  }
  return new Error(`Request failed (${response.status}). Please try again.`);
}
