# Installing Lead Outreach on Windows

This takes about 5 minutes. You do not need any technical knowledge. You need Windows 10 or 11.

---

## Step 1: Install Google Chrome (skip if you already have it)

Lead Outreach uses Google Chrome in the background to look at Google Maps.

1. Open <https://www.google.com/chrome/> in any browser.
2. Click **Download Chrome**, open the downloaded file, and follow the steps.

Not sure if you have it? Click the Start button and type **Chrome**. If "Google Chrome" appears,
you have it.

---

## Step 2: Download the installer

Your helper will send you a link or a file called **`LeadOutreachSetup.exe`**.
Save it (it usually goes to your **Downloads** folder).

---

## Step 3: Run the installer

1. Double-click **`LeadOutreachSetup.exe`**.
2. **You will probably see a blue box saying "Windows protected your PC".** This is normal.
   It appears because the app is new and has not paid for a Microsoft "signature". It does not
   mean there is a virus.
   - Click the small **More info** text.
   - Then click the **Run anyway** button that appears.
3. The installer opens. Click **Next**.
4. Tick **"Put a Lead Outreach icon on my Desktop"** if you want one. Click **Next**, then
   **Install**.
5. Leave **"Start Lead Outreach now"** ticked and click **Finish**.

You do **not** need an administrator password. The app installs just for your Windows user.

---

## Step 4: First launch

- Lead Outreach opens in your web browser at an address like `http://127.0.0.1:8765`.
  This page is only on your own computer, not on the internet.
- There is no separate window. The app runs quietly in the background while the browser page is
  open.
- Follow the steps at the top of the page: **About you → Gmail connection → Your email →
  Who to target → Run → Results**.
- **Windows Firewall:** if Windows asks whether Lead Outreach may use the network, you can click
  **Cancel** or **Allow**. Either is fine: the app only talks to your own computer and the
  internet, it does not need to accept connections from other computers.

**To open it again later:** Start Menu → **Lead Outreach** (or the Desktop icon).
If it is already running, this simply opens the page again.

**Bookmark tip:** you can bookmark `http://127.0.0.1:8765` in your browser. The bookmark only
works while Lead Outreach is running.

---

## Where your data lives

Everything you set up (settings, Gmail connection, businesses found, sent-email history, your
PDFs and log files) is saved in:

```
%APPDATA%\LeadOutreach
```

To open it: Start Menu → **Lead Outreach** → **Open my Lead Outreach data folder**.
(Or paste `%APPDATA%\LeadOutreach` into the address bar of File Explorer and press Enter.)

To back up your work, copy this folder to a USB stick or cloud drive.

---

## Updating to a new version

1. Get the new `LeadOutreachSetup.exe` from your helper.
2. Double-click it and click through the same steps as before (including **More info → Run
   anyway**).
3. The installer closes the old version and replaces it. **Your settings and lists are kept.**

---

## Uninstalling

1. Open **Settings → Apps → Installed apps** (Windows 11) or **Settings → Apps** (Windows 10).
2. Find **Lead Outreach**, click it (or the **⋯** next to it), then **Uninstall**.
3. You will be asked: **"Do you also want to delete your saved settings…?"**
   - **No** (recommended): keeps your data in case you install again later.
   - **Yes**: deletes everything, including your Gmail connection and lists.

---

## Troubleshooting: the top 8 problems

**1. "Windows protected your PC" and there is no "Run anyway" button.**
Click the small **More info** text first; the button then appears. If your antivirus deleted the
file, ask your helper; it is a "false alarm" that sometimes happens with new apps. Download it
again and allow it in your antivirus.

**2. A message says Google Chrome is not installed.**
Do Step 1 above, then open Lead Outreach again. You can still fill in your settings without
Chrome, but searching for businesses needs it.

**3. A message says "another program is already using port 8765".**
Restart your computer and open Lead Outreach again. If it keeps happening, tell your helper.

**4. Nothing seems to happen when I click the icon.**
Wait 20 seconds: the first start can be slow, especially while antivirus checks the app. Then
check your browser for a new tab. Still nothing? Open your browser and go to
`http://127.0.0.1:8765`.

**5. "Gmail rejected the password".**
You need an **App Password**, not your normal Gmail password. In the **Gmail connection** step,
follow the guide: turn on 2-Step Verification in your Google account, then create an App
Password, and paste the 16 letters (spaces do not matter).

**6. Searching finds no businesses, or stops early.**
Google may be showing "unusual traffic" checks because of too many searches. Stop for a few hours,
then try again with fewer areas. Also check that your internet connection works.

**7. My emails go to spam, or Gmail says I sent too many.**
Lower the **daily limit** (start with 20 to 50 a day) and keep a longer delay between emails.
Make your email short and personal. Gmail may pause sending for up to 24 hours if the limit is
reached; just wait.

**8. Something else went wrong / the app "stopped unexpectedly".**
Open your data folder (see "Where your data lives"), then the **logs** folder, and send the files
inside it to your helper. They contain no passwords.

**How do I fully close the app?** It closes when you restart or shut down the computer.
It is fine to leave it running: it uses very little memory when it is not working.
