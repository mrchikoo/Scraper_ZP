# Releasing Lead Outreach (for the maintainer)

The Windows installer is built on GitHub's Windows machines, so you can release from a Mac.

## One-time setup

1. Push this project to a GitHub repository (private is fine).
2. In the repo: **Settings → Actions → General → Workflow permissions** → choose
   **Read and write permissions** (needed to attach the installer to a Release).

## Cut a release

1. Make sure everything works locally: `packaging/build_local.sh test` and
   `packaging/build_local.sh run` (click through the app once).
2. Bump the version the backend reports in `/api/health` (ask the backend owner where it lives,
   e.g. `app/__init__.py`), commit.
3. Tag and push (the tag must start with `v`):

   ```
   git tag v1.0.0
   git push origin main --tags        # or your branch name
   ```

4. Open the repo's **Actions** tab → **Build Windows installer**. It takes about 10 minutes and:
   runs the tests, builds the app with PyInstaller, builds `LeadOutreachSetup.exe` with Inno
   Setup, installs it silently, starts it, checks `/api/health`, uninstalls it, and finally
   attaches the installer to a new **Release** named after the tag.
5. If it fails: click the red step to read the error. The smoke-test step prints the app's log
   files.

**Test build without a release:** Actions → Build Windows installer → **Run workflow**.
The installer is then under the run's **Artifacts** (a ZIP containing the .exe).

## Hand it to your users

1. Open the repo's **Releases** page, open the new release, and copy the link to
   `LeadOutreachSetup.exe` (or download it and send it via Google Drive / WhatsApp).
   If the repo is private, users cannot open GitHub links: send the file itself.
2. Send him [INSTALL_WINDOWS.md](INSTALL_WINDOWS.md) (or a short message): "Run it; on the blue
   'Windows protected your PC' box click **More info → Run anyway**; your settings are kept."
3. Ideally test the installer once on a real Windows PC before sending.

## Good to know

- The exe is **not code-signed**, hence the SmartScreen warning. A code-signing certificate
  (roughly USD 100–400/year) would remove it; add a signing step after PyInstaller and on the
  installer if you ever buy one.
- Antivirus false positives happen with PyInstaller apps. UPX is turned off to reduce them.
  If one triggers, report the file to the vendor as a false positive.
- Never change `AppId` in `packaging/installer.iss`: upgrades rely on it.
- Replace the placeholder icon by putting your own `packaging/icon.ico` in the repo.
- User data (`%APPDATA%\LeadOutreach`) survives updates; uninstall only removes it if the user says yes.
- Docker users: they just pull the new code and run `docker compose up -d --build`.
