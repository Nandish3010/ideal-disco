import { initializeApp } from "firebase/app";
import { getFirestore } from "firebase/firestore";

// Put the Firebase web config JSON string in web/.env.local as VITE_FIREBASE_CONFIG (see .env.example).
const app = initializeApp(JSON.parse(import.meta.env.VITE_FIREBASE_CONFIG));
export const db = getFirestore(app); // (default) database

// Web push for a cop going on duty. Asks for notification permission (call it straight from the tap, before any await,
// or Safari drops the gesture), returns the FCM token (registering the push worker); null when push is unavailable,
// denied or VITE_FIREBASE_VAPID_KEY is not set (Firebase console > Project settings > Cloud Messaging > Web Push
// certificates). Never throws: duty works without push.
export async function pushToken() {
  const vapidKey = import.meta.env.VITE_FIREBASE_VAPID_KEY;
  try {
    if (!vapidKey || typeof Notification === "undefined" || !("serviceWorker" in navigator))
      return null;
    if ((await Notification.requestPermission()) !== "granted") return null;
    const { getMessaging, getToken, isSupported } = await import("firebase/messaging");
    if (!(await isSupported())) return null;
    // The SDK registers /firebase-messaging-sw.js itself, under its own scope (/firebase-cloud-messaging-push-scope), so
    // it never replaces the app shell's /sw.js, which holds the root scope.
    return (await getToken(getMessaging(app), { vapidKey })) || null;
  } catch {
    return null;
  }
}
