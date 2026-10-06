// Shows the alert the API pushes (FCM web push: a notification plus a data payload) when no page of ours is on screen.
// With /cop open the page already speaks and shows the alert, so the push is skipped. No Firebase SDK is needed here:
// the push event carries the payload as JSON.
self.addEventListener("push", (event) => {
  let m = {};
  try {
    m = event.data ? event.data.json() : {};
  } catch {
    /* not JSON: show nothing */
  }
  const n = m.notification || {};
  const d = m.data || {};
  if (!n.title && !d.text) return;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
      if (wins.some((w) => w.visibilityState === "visible")) return;
      return self.registration.showNotification(n.title || d.stage || "Emergency vehicle", {
        body: n.body || d.text,
        tag: d.junction_id ? `${d.run_id}/${d.junction_id}/${d.stage}` : undefined,
        requireInteraction: true,
        data: { url: "/cop", audio_url: d.audio_url },
      });
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
      const open = wins.find((w) => new URL(w.url).pathname === "/cop") || wins[0];
      return open ? open.focus() : self.clients.openWindow("/cop");
    }),
  );
});
