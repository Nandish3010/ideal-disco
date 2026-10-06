import { initializeApp } from "firebase/app";
import { getFirestore } from "firebase/firestore";

// Put the Firebase web config JSON string in web/.env.local as VITE_FIREBASE_CONFIG (see .env.example).
const app = initializeApp(JSON.parse(import.meta.env.VITE_FIREBASE_CONFIG));
export const db = getFirestore(app); // (default) database

// Web push for a cop going on duty. Asks for notification permission (call it straight from the tap, before any await,
// or Safari drops the gesture), registers the push worker and returns the FCM token; null when push is unavailable,
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
    await navigator.serviceWorker.register("/firebase-messaging-sw.js");
    const serviceWorkerRegistration = await navigator.serviceWorker.ready;
    return (await getToken(getMessaging(app), { vapidKey, serviceWorkerRegistration })) || null;
  } catch {
    return null;
  }
}
