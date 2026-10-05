import { expect, test } from "vitest";
import { responseError } from "./http";

test("voice preview displays the useful detail without raw JSON", async () => {
  const error = await responseError(
    new Response(
      JSON.stringify({
        detail: "Groq voice is rate-limited (tokens per minute).",
      }),
      { status: 429 },
    ),
  );
  expect(error.message).toBe("Groq voice is rate-limited (tokens per minute).");
});

test("validation objects and proxy HTML do not leak into the notice", async () => {
  for (const body of [
    '{"detail":[{"input":"private"}]}',
    "<html>proxy failure</html>",
  ]) {
    expect(
      (await responseError(new Response(body, { status: 502 }))).message,
    ).toBe("Request failed (502). Please try again.");
  }
});
