# Lead Outreach: architecture contract (manager-owned; do not edit without asking)

Product: a Windows desktop-style app for a NON-TECHNICAL freelance marketer or small agency owner.
It scrapes small-business contact emails from Google Maps (any city the user types; areas are listed from OpenStreetMap), then sends the user's pitch email
(with the user's PDF attached) through their own Gmail. Everything is configured from a browser UI served
locally. The user has no Python, no VS Code, no terminal.

Origin: started as a Mumbai-targeted tool; now city-agnostic. Mumbai keeps a built-in offline area list.

## Layout

```
scraper/
  app/
    __init__.py
    __main__.py          # `python -m app` -> starts server, opens browser         [BACKEND]
    server.py            # Flask app + waitress, 127.0.0.1:8765 only                 [BACKEND]
    paths.py             # data dir resolution                                       [BACKEND]
    settings.py          # load/save settings.json, validation, secret masking       [BACKEND]
    engine/
      scraper.py         # Google Maps -> emails (port of old main.py)               [BACKEND]
      sender.py          # SMTP sender (port of old email_sender.py)                 [BACKEND]
      filters.py         # email filtering (port of old filters + run_areas rules)   [BACKEND]
      runner.py          # orchestrator thread, state, stop flag (old run_areas.py)  [BACKEND]
      areas.py           # city -> areas lookup (OSM)                                      [BACKEND]
      leads.py           # leads store, sent log, suppression list                   [BACKEND]
    web/                 # static UI, vanilla HTML/CSS/JS, NO build step, no CDN     [FRONTEND]
      index.html  app.css  app.js  (+ any extra files under web/)
  requirements.txt                                                                  [BACKEND]
  tests/                                                                            [BACKEND]
  packaging/             # PyInstaller spec, Inno Setup script, launcher, icon       [DEVOPS]
  Dockerfile  docker-compose.yml  .dockerignore                                     [DEVOPS]
  .github/workflows/build-windows.yml                                               [DEVOPS]
  README.md  INSTALL_WINDOWS.md  INSTALL_DOCKER.md  (plain-language, for the end user)      [DEVOPS]
```

Old root files (main.py, email_sender.py, run_areas.py, README.md, SCRAPER_README.md,
tech_searches.txt, useragents.txt) are the legacy source. BACKEND ports what is useful into
`app/engine/` then deletes the legacy files. DEVOPS rewrites README.md.

## Data dir (all user data, never inside the install dir)
`OUTREACH_DATA_DIR` env var, else Windows `%APPDATA%\LeadOutreach`, else `~/.lead_outreach`.
Docker uses `/data`. Contains: `settings.json`, `uploads/` (PDFs), `leads.json`,
`sent_log.txt`, `suppression.txt`, `logs/app.log`, `chrome_profile/`.
Packaged resources (useragents.txt etc.) ship read-only inside the app and are found via a
`resource_path()` helper that works under PyInstaller (`sys._MEIPASS`).

## settings.json schema
```json
{
  "profile": {"full_name": "", "business_name": "", "phone": "", "website": "", "services": ""},
  "smtp": {"email": "", "app_password": ""},
  "email": {"subject": "", "body": "", "attachments": ["file.pdf"]},
  "targeting": {"city": "Pune", "country": "in", "business_types": ["restaurants"], "areas": ["Koregaon Park"]},
  "limits": {"max_per_day": 100, "min_delay_s": 45, "max_delay_s": 150, "max_per_domain": 2}
}
```
Body placeholders: `{{my_name}} {{my_business}} {{my_phone}} {{my_website}} {{business_name}}`
(`business_name` = the scraped business's name; fall back to "there"/"team" if unknown).
Body is plain text typed by the user; the sender builds a text part + simple HTML part.
A non-removable opt-out footer is always appended ("If you'd rather not hear from me, just reply
STOP"), and addresses of anyone replying STOP can be added to `suppression.txt` via the UI.
`max_per_day` hard ceiling 400 regardless of what is typed. Default 100.

## HTTP API (JSON, all under /api, bound to 127.0.0.1)
| Method | Path | Notes |
|---|---|---|
| GET | /api/health | `{ok:true, version, chrome_found:bool, data_dir}` |
| GET | /api/settings | same schema; `smtp.app_password` is NEVER returned, instead `smtp.has_app_password:bool` |
| PUT | /api/settings | full or partial; empty/omitted `app_password` keeps the stored one; returns `{ok, errors:{field:msg}}` |
| POST | /api/smtp/test | logs in to smtp.gmail.com:465 with stored creds -> `{ok, message}` (plain-English message, e.g. "Gmail rejected the password: you need an App Password, not your normal one") |
| POST | /api/attachments | multipart `file`, PDF only, max 10 MB -> `{ok, name}` |
| GET | /api/attachments | `[{name,size}]` |
| DELETE | /api/attachments/<name> | |
| POST | /api/email/preview | body `{subject, body, business_name?}` -> `{subject, text, html}` rendered with settings.profile |
| POST | /api/email/test-send | sends the current email to the user's own address -> `{ok, message}` |
| GET | /api/areas?city=X | `{city, country, presets:[{name,lat,lng}], source, error, business_types:[{key,label}]}` areas inside X (OpenStreetMap, cached) + business-type presets; no `city` = the saved one |
| POST | /api/run/start | `{mode:"scrape"\|"send"\|"both"}` -> `{ok, message}`; refuses with a clear message if settings incomplete |
| POST | /api/run/stop | graceful stop -> `{ok}` |
| GET | /api/run/status | `{state:"idle"\|"running"\|"stopping", mode, current_area, areas_done, areas_total, leads_found, sent_total, sent_today, daily_cap, last_error}` |
| GET | /api/run/logs?since=N | `{next:int, lines:[str]}` plain-English log lines, ring buffer of 2000 |
| GET | /api/leads | `[{email, business_name, website, area, status:"new"\|"sent"\|"failed"\|"excluded", sent_at?}]` |
| POST | /api/leads/exclude | `{email}` adds to suppression list |
| GET | /api/leads/export.csv | CSV download |
| GET | / and /<static> | serves `app/web/` |

Errors: HTTP 200 with `{ok:false, message}` for expected problems (bad password, no chrome);
HTTP 4xx/5xx only for real bugs. Messages are written for a non-technical reader.

## UI requirements (FRONTEND)
Single page, wizard-like, large friendly controls, English, mobile-agnostic (desktop laptop).
Sections/tabs: 1 "About you" (profile) · 2 "Gmail connection" (email + App Password with a
step-by-step illustrated-in-text guide on creating a Gmail App Password, and a "Test connection"
button) · 3 "Your email" (subject, body editor with placeholder chips, live preview, attach PDF
CV/portfolio via drag-and-drop, "Send me a test email") · 4 "Who to target" (Mumbai areas
multi-select with search + select-all, business-type checkboxes) · 5 "Run" (Start/Stop, live
status, progress, live log, daily-limit meter) · 6 "Results" (leads table, filter by status,
exclude button, Export CSV). A setup-progress checklist at the top shows what is still missing.
Accessible (labels, contrast, keyboard), dark/light via prefers-color-scheme, no external
network requests (works offline except the scraping itself). No frameworks needing a build.
Until the backend exists the UI must degrade gracefully (clear "backend not reachable" state).

## Non-goals
No auth (localhost only), no cloud, no telemetry. Do not touch anything outside
this project folder.
