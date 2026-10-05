import { initializeApp } from "firebase/app";
import { getFirestore } from "firebase/firestore";

// Put the Firebase web config JSON string in web/.env.local as VITE_FIREBASE_CONFIG (see .env.example).
const app = initializeApp(JSON.parse(import.meta.env.VITE_FIREBASE_CONFIG));
export const db = getFirestore(app); // (default) database
