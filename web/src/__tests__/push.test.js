import { beforeEach, describe, expect, it, vi } from "vitest";

const getToken = vi.fn(async () => "fcm-token");
vi.mock("firebase/messaging", () => ({
  getMessaging: () => ({}),
  getToken,
  isSupported: async () => true,
}));

let permission, register;
beforeEach(() => {
  vi.resetModules();
  getToken.mockClear();
  vi.stubEnv("VITE_FIREBASE_CONFIG", '{"projectId":"p","appId":"1:2:web:3"}');
  vi.stubEnv("VITE_FIREBASE_VAPID_KEY", "vapid");
  permission = "granted";
  register = vi.fn(async () => ({}));
  vi.stubGlobal("Notification", { requestPermission: async () => permission });
  vi.stubGlobal("navigator", {
    serviceWorker: { register, ready: Promise.resolve({ scope: "/" }) },
  });
});
const run = async () => (await import("../firebase.js")).pushToken();

describe("pushToken", () => {
  it("returns the FCM token once permission is granted", async () => {
    expect(await run()).toBe("fcm-token");
    expect(register).toHaveBeenCalledWith("/firebase-messaging-sw.js");
    expect(getToken.mock.calls[0][1].vapidKey).toBe("vapid");
  });

  it("is null, without asking, when no VAPID key is configured", async () => {
    vi.stubEnv("VITE_FIREBASE_VAPID_KEY", "");
    expect(await run()).toBeNull();
    expect(register).not.toHaveBeenCalled();
  });

  it("is null when permission is denied or the token call fails", async () => {
    permission = "denied";
    expect(await run()).toBeNull();
    permission = "granted";
    getToken.mockRejectedValueOnce(new Error("no"));
    expect(await run()).toBeNull();
  });
});
