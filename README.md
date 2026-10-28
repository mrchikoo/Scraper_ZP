# Lead Outreach

Find small businesses in any city and email them your pitch, all from a simple page in your web browser.
You do not need to know anything about programming.

**What it does**

1. Looks up businesses on Google Maps (for example "cafes in Koregaon Park, Pune").
2. Visits their websites and collects their public contact email addresses.
3. Sends each one your email from your own Gmail, with your PDF (portfolio or rate card) attached.

Everything stays on your own computer.

---

## Step by step

### Step 1. Install Google Chrome

If you do not have it, download it free from <https://www.google.com/chrome>. The app uses Chrome quietly in the background to read Google Maps.

### Step 2. Download the app

1. Open the **Releases** page: <https://github.com/mrchikoo/lead-outreach/releases>
2. Under the newest release, click **LeadOutreachSetup.exe** to download it.

*(If there is no download there yet, ask your helper. The installer is still being prepared.)*

### Step 3. Install it

1. Double-click **LeadOutreachSetup.exe**.
2. Windows may show a blue box saying **"Windows protected your PC"**. This is normal for new programs. Click **More info**, then **Run anyway**.
3. Click **Next** and then **Install**. You do not need an administrator password.
4. Tick **Create a desktop shortcut** if you like, then click **Finish**.

### Step 4. Open the app

Double-click **Lead Outreach** on your desktop or in the Start menu. Your web browser opens a page with a checklist at the top. Keep that page open. Closing the browser tab does not stop the app.

### Step 5. Tell it about you

In the **About you** section, type your name, your business name, your phone number and your website. These fill in the blanks in your email automatically.

### Step 6. Connect your Gmail

The app sends emails through your Gmail account. For this you need a special **App Password**, not your normal password.

1. Go to <https://myaccount.google.com/security> and make sure **2-Step Verification** is **On**. Turn it on if it is not.
2. Go to <https://myaccount.google.com/apppasswords>.
3. Type a name, such as `Lead Outreach`, and click **Create**.
4. Google shows a **16-letter code**. Copy it.
5. Back in the app, in **Gmail connection**, type your Gmail address and paste the code.
6. Click **Test connection**. You should see a green success message.

Never type your normal Gmail password into the app.

### Step 7. Write your email

1. In **Your email**, a sample pitch is already filled in. Change the subject and the text to sound like you.
2. Click the small buttons such as **{{business_name}}** to drop in automatic blanks. The business name is filled in for each business.
3. Drag your **PDF** onto the upload box.
4. Click **Send me a test email** and look at it in your own inbox. Fix anything you do not like.

### Step 8. Choose who to target

In **Who to target**:

1. **Where?** Type the **city or region** you want to look in (for example `Pune`, `Dubai` or `Manchester`) and click **Find areas**. The app lists the areas inside that place. Tick the ones you want. Start with only one or two. If an area is missing, type its name in the box under the list and click **Add**. (Finding areas needs an internet connection; the list is saved afterwards.)
2. Pick the **size of business**: **Small businesses** (independent local shops and firms, SMEs), **Mid-sized businesses** (busy, established places and ones with several branches), or **All sizes**. Google Maps does not show business size, so the app guesses from the number of reviews and whether the business has several branches.
3. Tick the kinds of business (cafes, salons, gyms and so on).
4. Have your own **niche**? Type it in the "Your own niche" box (for example `yoga studios` or `wedding photographers`) and click **Add**.

### Step 9. Find businesses

1. Go to the **Run** section.
2. Choose **Find businesses** and click **Start**.
3. Watch the progress and the log. A search can take several minutes. You can click **Stop** at any time.

### Step 10. Check the results

Open the **Results** section. You see every business found, with its email address. Remove any you do not want to email by clicking **Don't email**.

### Step 11. Send your emails

1. In **Run**, choose **Send emails** (or **Do both** to search and send together) and click **Start**.
2. The app waits a random short time between emails. This is on purpose, so it looks natural and keeps your Gmail safe.
3. You can stop at any time. The app never emails the same person twice.

---

## Other way to install: download the code with Git

Use this if the installer is not available, or if you are on a Mac. It takes about 10 minutes, once.

### What to download first (all free)

| Program | Why | Where to get it |
|---|---|---|
| **Git** | Downloads the app's code | <https://git-scm.com/downloads> (click Next through the installer) |
| **Python 3.11 or newer** | Runs the app | <https://www.python.org/downloads/>. On Windows, **tick "Add python.exe to PATH"** on the first screen |
| **Google Chrome** | Reads Google Maps | <https://www.google.com/chrome> |

### Steps (Windows)

1. Open the **Start menu**, type `cmd` and press Enter. A black window opens.
2. Download the code. Type this and press Enter:

```
git clone https://github.com/mrchikoo/lead-outreach.git
```

3. Go into the folder:

```
cd lead-outreach
```

4. Set up the app (only the first time):

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

5. Start the app:

```
python -m app
```

Your browser opens the app. Then carry on from **Step 5** above. Leave the black window open while you use the app.

### Next time

Open `cmd`, then type these one after another:

```
cd lead-outreach
.venv\Scripts\activate
python -m app
```

To get the newest version of the app, run `git pull` inside the `lead-outreach` folder first.

On a Mac, use `python3` instead of `python`, and `source .venv/bin/activate` instead of `.venv\Scripts\activate`.

---

## Please send responsibly

- **Start small.** Send 20 to 50 emails a day in the first week. The app allows at most 400 a day and suggests 100.
- **Only email businesses that could really use your service.** Keep your message short, honest and personal.
- **Respect "no".** Every email ends with a line telling people they can reply "STOP". If someone replies STOP or asks not to be contacted, click **Don't email** next to them in **Results** straight away.
- **Keep your list private.** Do not sell or share the email addresses.
- **Use Google Maps gently.** Searching it automatically may go against Google's rules. Search a few areas at a time, not all day. If Google starts showing "unusual traffic" checks, stop for the day.

This is general guidance, not legal advice.

---

## Common problems

| Problem | What to do |
|---|---|
| "Test connection" fails | Check that 2-Step Verification is on and that you pasted the 16-letter App Password, not your normal password. |
| The page does not open | Open your browser and go to <http://127.0.0.1:8765>. |
| It says Chrome was not found | Install Google Chrome (Step 1), then open the app again. |
| No businesses are found | Try a different area or business type, wait a few minutes, and try again. |
| Gmail says the daily limit is reached | Stop sending and try again tomorrow. Lower the daily limit next time. |

---

## Where your information is saved

Your settings, your found businesses, your sent history and your PDFs are saved on your own computer in `%APPDATA%\LeadOutreach`. Paste that into the address bar of File Explorer to open it. Uninstalling the app asks before deleting it.

---

## For your helper

- Run from source: `python -m app`, then open <http://127.0.0.1:8765>.
- Windows install details: [INSTALL_WINDOWS.md](INSTALL_WINDOWS.md). Docker option: [INSTALL_DOCKER.md](INSTALL_DOCKER.md).
- Making a new installer: [RELEASING.md](RELEASING.md). How the code is organised: [ARCHITECTURE.md](ARCHITECTURE.md).
