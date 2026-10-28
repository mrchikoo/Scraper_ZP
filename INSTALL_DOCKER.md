# Running Lead Outreach with Docker

Use this only if you (or your helper) prefer Docker, or you are on a Mac or Linux computer.
On a normal Windows PC, the [Windows installer](INSTALL_WINDOWS.md) is easier.

Docker runs Lead Outreach inside a small sealed "box" on your computer, with its own copy of
Chrome included. You do not need to install Chrome or Python yourself.

---

## 1. Install Docker Desktop (one time)

1. Go to <https://www.docker.com/products/docker-desktop/> and download Docker Desktop for your
   computer (Windows, Mac with Apple chip, or Mac with Intel chip).
2. Install it and start it. Wait until the Docker whale icon says **"Docker Desktop is running"**.
3. On Windows, if it asks to install or update "WSL", say yes and restart when asked.

## 2. Get the Lead Outreach folder

Your helper will give you the Lead Outreach folder (for example as a ZIP file). Unzip it somewhere
easy, such as your Documents folder.

## 3. Start Lead Outreach

1. Open the Lead Outreach folder.
2. Open a terminal **in that folder**:
   - **Windows:** click the address bar of the File Explorer window, type `cmd`, press Enter.
   - **Mac:** right-click the folder → **New Terminal at Folder**.
3. Type this and press Enter:

   ```
   docker compose up -d --build
   ```

   The first time takes a few minutes (it downloads Chrome and other parts). Later starts take
   seconds.
4. Open your browser and go to **<http://127.0.0.1:8765>**.

Lead Outreach now starts automatically whenever Docker Desktop is running, until you stop it.

## 4. Stop Lead Outreach

In a terminal in the same folder:

```
docker compose down
```

Your settings and lists are **kept** (they live in a Docker "volume" called `outreach-data`).

## Updating

Replace the folder with the new one from your helper, then run `docker compose up -d --build`
again. Your data is kept.

## Deleting everything (including your data)

```
docker compose down -v
```

The `-v` deletes your saved settings, Gmail connection, lists and PDFs. There is no undo.

---

## Problems

- **"Cannot connect to the Docker daemon" / "docker: command not found"**: Docker Desktop is not
  running. Start it, wait for "running", try again.
- **The page does not open**: wait 30 seconds after starting, then reload. To see what the app is
  doing, run `docker compose logs --tail 100`.
- **"port is already allocated"**: something else uses port 8765. Close it, or ask your helper to
  change the first `8765` in `docker-compose.yml` (e.g. `127.0.0.1:8766:8765`) and then open
  <http://127.0.0.1:8766>.

---

## For the helper

- The app is published **only on 127.0.0.1** of the host. Inside the container it binds
  `0.0.0.0` (`OUTREACH_HOST=0.0.0.0`) so Docker can forward the port; there is no login, so never
  change the compose port line to `0.0.0.0:8765:8765` or `8765:8765`.
- Data: named volume `outreach-data` mounted at `/data` (`OUTREACH_DATA_DIR=/data`).
  Back it up with:
  `docker run --rm -v outreach-data:/data -v "$PWD":/backup busybox tar czf /backup/outreach-data.tgz -C /data .`
  (Compose may prefix the volume name with the folder name; check `docker volume ls`.)
- Chrome: Debian `chromium` + `chromium-driver` (amd64 and arm64). The image sets
  `OUTREACH_CHROME_BINARY=/usr/bin/chromium`, `OUTREACH_CHROMEDRIVER=/usr/bin/chromedriver`,
  `OUTREACH_IN_DOCKER=1` and `SE_OFFLINE=true` so Selenium Manager does not try to download anything.
  `shm_size: 1gb` avoids Chrome crashes.
- Runs as non-root user `outreach` (uid 10001) under `tini`. Health check: `GET /api/health`
  must return `{"ok": true}`; see `docker inspect --format '{{.State.Health.Status}}' lead-outreach`.

### Build-time check of the backend contract

The Docker image and the Windows launcher depend on the backend honouring these environment
variables. Check before building (the GitHub workflow does the same check automatically):

```
grep -rqE "OUTREACH_HOST"       app/ && \
grep -rqE "OUTREACH_NO_BROWSER" app/ && \
grep -rqE "OUTREACH_PORT"       app/ && \
grep -rqE "OUTREACH_DATA_DIR"   app/ && echo "backend contract OK"
```

| Variable | Default | Meaning |
|---|---|---|
| `OUTREACH_HOST` | `127.0.0.1` | address the server binds to (`0.0.0.0` only inside Docker) |
| `OUTREACH_PORT` | `8765` | port |
| `OUTREACH_DATA_DIR` | `%APPDATA%\LeadOutreach` or `~/.lead_outreach` | where all user data goes |
| `OUTREACH_NO_BROWSER` | unset | `1` = do not open a browser on start |
| `OUTREACH_CHROME_BINARY` / `OUTREACH_CHROMEDRIVER` | unset | explicit Chrome / chromedriver paths (Docker) |
| `OUTREACH_IN_DOCKER` | unset | `1` = add `--no-sandbox --disable-dev-shm-usage` to Chrome |

Quick manual test after `docker compose up -d --build`:

```
curl -fsS http://127.0.0.1:8765/api/health
```
