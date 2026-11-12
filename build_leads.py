#!/usr/bin/env python3
"""Build a verified B2B lead list of private French secondary schools.

Source: French Ministry of Education open directory (Opendatasoft API).
Usage: python build_leads.py --region "Ile-de-France" --types Lycée Collège --count 20
"""
import argparse, csv, html, re, subprocess, sys, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from urllib.parse import urljoin, urlparse
import requests

API = "https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets/fr-en-annuaire-education/records"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
COLUMNS = ["school_name", "school_type", "uai_id", "address", "postcode", "city",
           "departement", "phone_intl", "official_email", "official_email_mx_ok",
           "website", "website_status", "website_email", "contact_page_url",
           "source_directory_url", "verified_on", "notes"]
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
JUNK_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js")


def fetch_directory(region, types):
    tq = " or ".join('type_etablissement="%s"' % t for t in types)
    where = ('statut_public_prive="Privé" and libelle_region="%s" and (%s) '
             'and web is not null and etat="OUVERT"' % (region, tq))
    rows, offset = [], 0
    while True:
        r = requests.get(API, params={"where": where, "limit": 100, "offset": offset,
                                      "order_by": "identifiant_de_l_etablissement"}, timeout=60)
        r.raise_for_status()
        res = r.json()["results"]
        rows += res
        if len(res) < 100:
            break
        offset += 100
    return [x for x in rows if (x.get("web") or "").strip()]


def norm_url(u):
    u = u.strip()
    if not re.match(r"^https?://", u, re.I):
        u = "http://" + u
    return u


def host_of(u):
    h = (urlparse(norm_url(u)).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def base_domain(h):
    p = h.split(".")
    return ".".join(p[-2:]) if len(p) >= 2 else h


def phone_intl(t):
    if not t:
        return ""
    d = re.sub(r"\D", "", t)
    if d.startswith("0033"):
        d = d[4:]
    elif d.startswith("33") and len(d) == 11:
        d = d[2:]
    elif d.startswith("0"):
        d = d[1:]
    return "+33" + d if len(d) == 9 else ""


def mx_ok(domain):
    try:
        out = subprocess.run(["nslookup", "-type=mx", domain], capture_output=True,
                             text=True, timeout=15).stdout.lower()
        return "mail exchanger" in out
    except Exception:
        return False


def get(url):
    return requests.get(url, headers={"User-Agent": UA, "Accept-Language": "fr-FR,fr;q=0.9"},
                        timeout=10, allow_redirects=True)


GENERIC = ("contact", "secretariat", "accueil", "info", "direction", "ecole", "college", "lycee",
           "inscription", "admission", "communication", "scolarite", "standard", "mail", "bonjour",
           "etablissement", "administration", "vie-scolaire", "viescolaire", "cdi", "comptabilite",
           "esta", "maule", "magnanville")


def is_generic(local):
    l = local.lower()
    return ("test" not in l) and any(g in l for g in GENERIC)


def extract_emails(text, own_domains):
    text = html.unescape(text)
    found = []
    for m in EMAIL_RE.findall(text):
        e = m.strip(".").lower()
        if e.endswith(JUNK_EXT):
            continue
        local, dom = e.split("@")
        if base_domain(dom) in own_domains and is_generic(local) and e not in found:
            found.append(e)
    return found


def find_contact_link(page, base):
    for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', page, re.I | re.S):
        href, label = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).lower()
        if href.lower().startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        if "contact" in href.lower() or "contact" in label:
            return urljoin(base, href)
    return ""


def check_site(rec):
    """Return dict of website verification results."""
    out = {"website_status": "", "final_url": "", "website_email": "", "contact_page_url": "", "note": ""}
    url = norm_url(rec["web"])
    own = {base_domain(host_of(url))}
    mail = (rec.get("mail") or "").lower()
    if "@" in mail:
        own.add(base_domain(mail.split("@")[1]))
    try:
        r = get(url)
    except requests.RequestException as e:
        out["website_status"] = "error: " + type(e).__name__
        return out
    out["website_status"] = str(r.status_code)
    out["final_url"] = r.url
    if r.status_code >= 400:
        return out
    # Final host may differ from directory domain (redirect): accept it as the school's own
    own.add(base_domain(host_of(r.url)))
    emails = extract_emails(r.text, own)
    link = find_contact_link(r.text, r.url)
    if link:
        try:
            r2 = get(link)
            if r2.status_code < 400:
                out["contact_page_url"] = r2.url
                for e in extract_emails(r2.text, own):
                    if e not in emails:
                        emails.append(e)
        except requests.RequestException:
            out["note"] = "contact page fetch failed"
    out["website_email"] = "; ".join(emails[:3])
    return out


def select(rows, count):
    """Deterministic: sort by UAI per departement, round-robin across departements,
    lycees before colleges, skipping duplicate UAI / website domain."""
    seen_uai, seen_dom = set(), set()
    groups = defaultdict(list)
    for r in sorted(rows, key=lambda x: (0 if x["type_etablissement"] == "Lycée" else 1,
                                         x["identifiant_de_l_etablissement"])):
        uai, dom = r["identifiant_de_l_etablissement"], base_domain(host_of(r["web"]))
        if uai in seen_uai or dom in seen_dom or not dom:
            continue
        seen_uai.add(uai); seen_dom.add(dom)
        groups[r["libelle_departement"]].append(r)
    chosen, keys = [], sorted(groups)
    while len(chosen) < count and any(groups[k] for k in keys):
        for k in keys:
            if groups[k] and len(chosen) < count:
                chosen.append(groups[k].pop(0))
    return chosen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="Ile-de-France")
    ap.add_argument("--types", nargs="+", default=["Lycée", "Collège"])
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--out", default="private_schools_idf_sample")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    t0 = time.time()
    today = date.today().isoformat()
    pool = fetch_directory(a.region, a.types)
    print("directory candidates:", len(pool))
    chosen = select(pool, a.count)
    print("selected:", len(chosen))
    with ThreadPoolExecutor(a.workers) as ex:
        sites = list(ex.map(check_site, chosen))
    mx_cache = {}
    out = []
    for rec, s in zip(chosen, sites):
        uai = rec["identifiant_de_l_etablissement"]
        mail = (rec.get("mail") or "").strip().lower()
        mxv = ""
        if "@" in mail:
            dom = mail.split("@")[1]
            if dom not in mx_cache:
                mx_cache[dom] = mx_ok(dom)
            mxv = "yes" if mx_cache[dom] else "no"
        st = s["website_status"]
        live = st.isdigit() and int(st) < 400
        notes = []
        if rec.get("type_contrat_prive"):
            notes.append("contract: " + rec["type_contrat_prive"].title())
        if not live:
            notes.append("website not reachable (%s)" % (st or "n/a"))
        elif s["final_url"] and host_of(s["final_url"]) != host_of(rec["web"]):
            notes.append("website redirects to " + host_of(s["final_url"]))
        if not mail:
            notes.append("no official email in directory")
        elif mxv == "no":
            notes.append("official email domain has no MX")
        if live and not s["website_email"]:
            notes.append("no own-domain email found on site")
        if s["note"]:
            notes.append(s["note"])
        out.append({
            "school_name": rec["nom_etablissement"], "school_type": rec["type_etablissement"],
            "uai_id": uai,
            "address": ", ".join(x for x in [rec.get("adresse_1"), rec.get("adresse_2")] if x),
            "postcode": rec.get("code_postal") or "", "city": rec.get("nom_commune") or "",
            "departement": rec.get("libelle_departement") or "",
            "phone_intl": phone_intl(rec.get("telephone")),
            "official_email": mail, "official_email_mx_ok": mxv,
            "website": s["final_url"] if live else norm_url(rec["web"]),
            "website_status": ("live (%s)" % st) if live else ("down (%s)" % (st or "n/a")),
            "website_email": s["website_email"], "contact_page_url": s["contact_page_url"],
            "source_directory_url": "https://data.education.gouv.fr/explore/dataset/fr-en-annuaire-education/table/?q=" + uai,
            "verified_on": today, "notes": "; ".join(notes)})
    # duplicate check on output
    assert len({r["uai_id"] for r in out}) == len(out), "duplicate UAI"
    assert len({base_domain(host_of(r["website"])) for r in out}) == len(out), "duplicate domain"
    with open(a.out + ".csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, COLUMNS); w.writeheader(); w.writerows(out)
    try:
        import openpyxl
        wb = openpyxl.Workbook(); ws = wb.active; ws.title = "leads"
        ws.append(COLUMNS)
        for r in out:
            ws.append([r[c] for c in COLUMNS])
        for i, c in enumerate(COLUMNS, 1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = min(48, max(12, len(c) + 4))
        ws.freeze_panes = "A2"
        wb.save(a.out + ".xlsx")
    except ImportError:
        print("openpyxl missing: xlsx skipped")
    live = sum(r["website_status"].startswith("live") for r in out)
    print("rows:", len(out), "live:", live,
          "mx_ok:", sum(r["official_email_mx_ok"] == "yes" for r in out),
          "website_email:", sum(bool(r["website_email"]) for r in out),
          "seconds: %.0f" % (time.time() - t0))


if __name__ == "__main__":
    sys.exit(main())
