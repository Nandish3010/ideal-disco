# The React PWA's site. Content is deployed by deploy-web.yml (firebase deploy --only hosting).
resource "google_firebase_hosting_site" "web" {
  provider = google-beta
  project  = var.project_id
  site_id  = var.project_id
}

# Browser key for Maps JavaScript (referrer restricted) and the server key for Routes, Places and Roads (API restricted).
# The key strings are not outputs here: the server key lives in Secret Manager, the browser key in the VITE_MAPS_BROWSER_KEY
# repository variable. The Firebase web key ("Browser key (auto created by Firebase)") is owned by Firebase and left out.
resource "google_apikeys_key" "maps_browser" {
  name         = "19fa6f8a-8c5c-4ebf-8479-abeebe26bddc"
  display_name = "corridor-maps-browser"
  restrictions {
    api_targets {
      service = "maps-backend.googleapis.com"
    }
    browser_key_restrictions {
      allowed_referrers = [
        "https://green-corridor-2026.web.app/*",
        "https://green-corridor-2026.firebaseapp.com/*",
        "http://localhost:*/*",
        "http://127.0.0.1:*/*",
      ]
    }
  }
  depends_on = [google_project_service.enabled]
}

resource "google_apikeys_key" "maps_server" {
  name         = "e9a95e44-df05-4c3d-a73d-2db07a509294"
  display_name = "corridor-maps-server-2"
  restrictions {
    api_targets {
      service = "routes.googleapis.com"
    }
    api_targets {
      service = "places.googleapis.com"
    }
    api_targets {
      service = "roads.googleapis.com"
    }
  }
  depends_on = [google_project_service.enabled]
}
