#!/usr/bin/env python3
"""Fake backend for previewing the UI. Stdlib only.
Run:  python3 dev-mock-server.py [port]   then open http://127.0.0.1:8766/
Query tweak: set env MOCK_EMPTY=1 to start with empty settings (first-run look)."""
import json, os, re, sys, time, threading, mimetypes
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote

HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "web")
AREAS = ["Andheri West", "Andheri East", "Bandra West", "Bandra East", "Juhu", "Powai", "Colaba", "Lower Parel",
         "Worli", "Dadar", "Malad West", "Goregaon East", "Borivali West", "Kurla", "Chembur", "Ghatkopar",
         "Vile Parle", "Santacruz", "Khar West", "Mulund West", "Thane West", "Navi Mumbai - Vashi"]
TYPES = [("restaurants", "Restaurants"), ("cafes", "Cafes"), ("salons", "Salons and spas"), ("gyms", "Gyms"),
         ("clinics", "Clinics"), ("boutiques", "Clothing boutiques"), ("coaching", "Coaching classes")]
empty = os.environ.get("MOCK_EMPTY") == "1"
settings = {
    "profile": {"full_name": "", "business_name": "", "phone": "", "website": "", "services": ""},
    "smtp": {"email": "", "app_password": ""},
    "email": {"subject": "", "body": "", "attachments": []},
    "targeting": {"city": "Mumbai", "business_types": [], "areas": []},
    "limits": {"max_per_day": 100, "min_delay_s": 45, "max_delay_s": 150, "max_per_domain": 2},
}
if not empty:
    settings["profile"].update(full_name="Alex Morgan", business_name="Acme Digital", phone="+91 98200 00000")
    settings["smtp"]["email"] = "alex@gmail.com"
    settings["targeting"].update(business_types=["restaurants", "cafes"], areas=["Bandra West", "Juhu"])
attachments = []
logs = []
leads = [{"email": "hello@%s.in" % n.lower().replace(" ", ""), "business_name": n + " Cafe", "website": n.lower() + ".in",
          "area": AREAS[i % len(AREAS)], "status": ["new", "sent", "failed", "excluded", "sent"][i % 5],
          "sent_at": "2026-10-25T10:%02d:00" % i} for i, n in enumerate(
    ["Sunrise", "Blue Tokai", "Chai Point", "Moonlight", "Spice Route", "Green Leaf", "Urban Bites", "Cafe Mocha"])]
run = {"state": "idle", "mode": "both", "areas_done": 0, "areas_total": 0, "leads_found": len(leads), "sent_total": 2,
       "sent_today": 2, "last_error": None, "current_area": ""}
lock = threading.Lock()

def log(m):
    logs.append(time.strftime("%H:%M:%S ") + m)

def worker():
    while run["state"] in ("running", "stopping") and run["areas_done"] < run["areas_total"]:
        time.sleep(2)
        with lock:
            if run["state"] == "stopping":
                break
            a = settings["targeting"]["areas"][run["areas_done"]]
            run["current_area"] = a
            log("Looking for businesses in %s..." % a)
            run["leads_found"] += 3; run["areas_done"] += 1
            run["sent_total"] += 1; run["sent_today"] += 1
            log("Found 3 new emails. Sent 1 email.")
    with lock:
        log("Stopped." if run["state"] == "stopping" else "All done. Well done!")
        run["state"] = "idle"; run["current_area"] = ""

def masked():
    s = json.loads(json.dumps(settings))
    s["smtp"]["has_app_password"] = bool(settings["smtp"]["app_password"]); s["smtp"].pop("app_password")
    return s

def merge(dst, src):
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            if k == "smtp" and not v.get("app_password"): v = {x: y for x, y in v.items() if x != "app_password"}
            merge(dst[k], v)
        else: dst[k] = v

def render(t, name):
    p = settings["profile"]
    m = {"my_name": p["full_name"], "my_business": p["business_name"], "my_phone": p["phone"],
         "my_website": p["website"], "business_name": name or "there"}
    return re.sub(r"\{\{(\w+)\}\}", lambda x: m.get(x.group(1), x.group(0)), t)

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, obj, code=200, ctype="application/json", extra=None):
        data = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(data)
    def body(self):
        n = int(self.headers.get("Content-Length") or 0); return self.rfile.read(n) if n else b""
    def js(self):
        try: return json.loads(self.body() or b"{}")
        except Exception: return {}

    def do_GET(self):
        u = urlparse(self.path); p = u.path
        if p == "/api/health": return self.send({"ok": True, "version": "0.1-mock", "chrome_found": True, "data_dir": "/mock"})
        if p == "/api/settings": return self.send(masked())
        if p == "/api/attachments": return self.send(attachments)
        if p == "/api/areas":
            return self.send({"city": "Mumbai", "presets": [{"name": a, "lat": 19.0, "lng": 72.8} for a in AREAS],
                              "business_types": [{"key": k, "label": l} for k, l in TYPES]})
        if p == "/api/run/status":
            return self.send(dict(run, daily_cap=settings["limits"]["max_per_day"]))
        if p == "/api/run/logs":
            since = int(parse_qs(u.query).get("since", ["0"])[0]); return self.send({"next": len(logs), "lines": logs[since:]})
        if p == "/api/leads": return self.send(leads)
        if p == "/api/leads/export.csv":
            rows = ["email,business_name,website,area,status"] + ["%s,%s,%s,%s,%s" % (l["email"], l["business_name"], l["website"], l["area"], l["status"]) for l in leads]
            return self.send("\n".join(rows).encode(), ctype="text/csv", extra={"Content-Disposition": "attachment; filename=leads.csv"})
        if p.startswith("/api/"): return self.send({"message": "not found"}, 404)
        f = os.path.normpath(os.path.join(HERE, "index.html" if p == "/" else unquote(p).lstrip("/")))
        if not f.startswith(HERE) or not os.path.isfile(f): return self.send(b"not found", 404, "text/plain")
        self.send(open(f, "rb").read(), ctype=mimetypes.guess_type(f)[0] or "application/octet-stream")

    def do_PUT(self):
        d = self.js(); errors = {}
        if "smtp" in d and d["smtp"].get("email") and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", d["smtp"]["email"]):
            errors["smtp.email"] = "That does not look like an email address."
        pw = (d.get("smtp") or {}).get("app_password")
        if pw and len(pw.replace(" ", "")) != 16: errors["smtp.app_password"] = "An App Password has 16 letters. Please copy it again from Google."
        cap = (d.get("limits") or {}).get("max_per_day")
        if cap != "" and cap is not None and (not isinstance(cap, int) or cap < 1): errors["limits.max_per_day"] = "Please type a whole number, 1 or more."
        if errors: return self.send({"ok": False, "errors": errors})
        if cap and cap > 400: d["limits"]["max_per_day"] = 400
        merge(settings, d); self.send({"ok": True, "errors": {}})

    def do_POST(self):
        p = urlparse(self.path).path
        if p == "/api/smtp/test":
            time.sleep(1)
            if not settings["smtp"]["app_password"]: return self.send({"ok": False, "message": "Gmail rejected the password: you need an App Password, not your normal one."})
            return self.send({"ok": True, "message": "Connected to Gmail as %s." % settings["smtp"]["email"]})
        if p == "/api/attachments":
            raw = self.body(); m = re.search(rb'filename="([^"]+)"', raw)
            name = m.group(1).decode() if m else "file.pdf"
            attachments.append({"name": name, "size": len(raw)}); return self.send({"ok": True, "name": name})
        if p == "/api/email/preview":
            d = self.js(); return self.send({"subject": render(d.get("subject", ""), d.get("business_name")),
                "text": render(d.get("body", ""), d.get("business_name")) + "\n\n--\nIf you'd rather not hear from me, just reply STOP.", "html": ""})
        if p == "/api/email/test-send":
            time.sleep(1); return self.send({"ok": True, "message": "Sent. Please check your inbox at %s." % settings["smtp"]["email"]})
        if p == "/api/run/start":
            d = self.js()
            if not settings["targeting"]["areas"]: return self.send({"ok": False, "message": "Please pick at least one area first."})
            with lock:
                run.update(state="running", mode=d.get("mode", "both"), areas_done=0, areas_total=len(settings["targeting"]["areas"]))
                log("Starting. Mode: %s." % run["mode"])
            threading.Thread(target=worker, daemon=True).start(); return self.send({"ok": True, "message": "Started."})
        if p == "/api/run/stop":
            run["state"] = "stopping"; log("Stop requested."); return self.send({"ok": True})
        if p == "/api/leads/exclude":
            e = self.js().get("email")
            for l in leads:
                if l["email"] == e: l["status"] = "excluded"
            return self.send({"ok": True})
        self.send({"message": "not found"}, 404)

    def do_DELETE(self):
        n = unquote(urlparse(self.path).path.rsplit("/", 1)[-1])
        attachments[:] = [a for a in attachments if a["name"] != n]; self.send({"ok": True})

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
    print("Mock UI at http://127.0.0.1:%d/" % port)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
