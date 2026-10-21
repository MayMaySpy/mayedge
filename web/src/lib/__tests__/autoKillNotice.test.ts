import { describe, expect, it } from "vitest";
import { AUTO_KILL_NOTICE_UNSEEN, autoKillNotice, type AutoKillNoticeSeen } from "@/lib/autoKillNotice";

function run(messages: [number | null, string | null][]): (string | null)[] {
  let seen: AutoKillNoticeSeen = AUTO_KILL_NOTICE_UNSEEN;
  return messages.map(([firedAt, status]) => {
    const out = autoKillNotice(seen, firedAt, status);
    seen = out.seen;
    return out.notice;
  });
}

describe("autoKillNotice", () => {
  it("stays quiet about the last fire the server resends on connect", () => {
    expect(run([[1000, "killed"], [1000, "killed"]])).toEqual([null, null]);
  });

  it("toasts a new fire once, whatever its retries report", () => {
    expect(run([[null, null], [2000, null], [2000, "error"], [2000, "killed"], [2000, "killed"]])).toEqual(
      [null, "fired", null, null, null]
    );
  });

  it("toasts once more when the flatten could not finish", () => {
    expect(run([[1000, "killed"], [2000, null], [2000, "killed"], [2000, "partial"], [2000, "partial"]])).toEqual(
      [null, "fired", null, "partial", null]
    );
  });

  it("toasts the next fire too", () => {
    expect(run([[1000, "killed"], [2000, null], [3000, null]])).toEqual([null, "fired", "fired"]);
  });
});
