import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import argparse
from urllib.parse import urljoin, quote

from zoneinfo import ZoneInfo
import re
from difflib import SequenceMatcher
from typing import Dict, List, Tuple, Set, Optional, Any
import itertools

import requests
from bs4 import BeautifulSoup

try:
    from wcwidth import wcswidth  # type: ignore
except Exception:
    wcswidth = None  # type: ignore

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

# ---- Config ----
LOGIN_URL = "https://intranet.crick.ac.uk/user/login?destination="

# CrickNet Interest Group event pages + the matching key used in the JSON export
GROUPS = [
    {"display": "Cancer", "json": "Cancer", "url": "https://intranet.crick.ac.uk/group/164/events"},
    {"display": "Development and Stem Cells", "json": "DSC", "url": "https://intranet.crick.ac.uk/group/167/events"},
    {"display": "Genes to Cells", "json": "GTC", "url": "https://intranet.crick.ac.uk/group/409/events"},
    {"display": "Immunology", "json": "Immunology", "url": "https://intranet.crick.ac.uk/group/168/events"},
    {"display": "Host and Pathogen", "json": "H&P", "url": "https://intranet.crick.ac.uk/group/169/events"},
    {"display": "Neuroscience", "json": "NIG", "url": "https://intranet.crick.ac.uk/group/170/events"},
    {"display": "Structural & Chemical Biology", "json": "SCB", "url": "https://intranet.crick.ac.uk/group/171/events"},
]

# Email Configuration
EMAIL_CONFIG = {
    "to": "email1",
    "cc": "cc1,cc2"
}

# External website seminar listing
EXTERNAL_BASE_URL = "https://www.crick.ac.uk"
EXTERNAL_LISTING_URL = EXTERNAL_BASE_URL + "/whats-on/seminars-lectures-and-symposia"
EXTERNAL_EVENT_TYPE_ID = "71"  # seminar filter
EXTERNAL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CrickNetChecker/1.0)"
}

# JSON name/code -> website group label
JSON_TO_WEBSITE_GROUP = {
    "Cancer": "Cancer",
    "DSC": "Development and Stem Cells",
    "Development and Stem Cells": "Development and Stem Cells",
    "GTC": "Genes to Cells",
    "Genes to Cells": "Genes to Cells",
    "Immunology": "Immunology",
    "H&P": "Host and Pathogen",
    "Host and Pathogen": "Host and Pathogen",
    "NIG": "Neuroscience",
    "Neuroscience": "Neuroscience",
    "SCB": "Structural and Chemical Biology",
    "Structural & Chemical Biology": "Structural and Chemical Biology",
    "Structural and Chemical Biology": "Structural and Chemical Biology",
}

LOCAL_TZ = ZoneInfo("Europe/London")
MIN_FUZZY_SCORE = 0.80 
PRIORITY_WINDOW_DAYS = 14

# SharePoint JSON export (produced by Power Automate)
SHAREPOINT_SITE = "https://thefranciscrickinstitute.sharepoint.com"
SHAREPOINT_TRIGGER_FOLDER_URL = (
    "https://thefranciscrickinstitute.sharepoint.com/sites/"
    "ScienceOperationsAdministration/Shared%20Documents/Forms/AllItems.aspx"
    "?id=/sites/ScienceOperationsAdministration/Shared%20Documents/Interest%20Groups/"
    "IG%20Oversight/Trigger&viewid=e732c5a8-f9c6-4fad-808e-2b431d730a69"
)

# 1. Update this path to match your folder structure exactly
TRIGGER_FOLDER_REL_PATH = "/sites/ScienceOperationsAdministration/Shared Documents/Interest Groups/IG Oversight/Trigger"
TRIGGER_FILENAME = "trigger.txt"

# 2. Keep your existing download path, but ensure it matches the user URL provided
SHAREPOINT_SERVER_RELATIVE_PATH = (
    "/sites/ScienceOperationsAdministration/Shared Documents/"
    "Interest Groups/IG Oversight/crick_talk_data_extract.json"
)
SHAREPOINT_DOWNLOAD_URL = (
    f"{SHAREPOINT_SITE}/sites/ScienceOperationsAdministration/_api/web"
    f"/GetFileByServerRelativeUrl('{SHAREPOINT_SERVER_RELATIVE_PATH}')/$value"
)

LOCAL_JSON_PATH = str(Path(__file__).resolve().parent / "crick_talk_data_extract.json")

CHROME_CHANNEL = "chrome"
PROFILE_DIR = str(Path.home() / "Library" / "Application Support" / "CrickNetChecker" / "profile")

# Selectors
SSO_BUTTON = 'a[title="Login using Crick SSO"]'
PROFILE_BUTTON = 'a[title="Profile"][href="/user"]'

ROW_SELECTOR = ".views-row"
TITLE_SELECTOR = "h4 a span"
LINK_SELECTOR = "h4 a"

# Speaker / lab blocks in teaser footer panel
SPEAKER_GROUP_SELECTOR = ".item-group-type-session-speaker-embed .item-group-inner"
SPEAKER_NAME_SELECTOR = "span.font-bold"
SPEAKER_LAB_SELECTOR = ".text-label.text-grey div"


# ---------------------------
# Utilities
# ---------------------------
def safe_inner_text(locator) -> str:
    try:
        if locator.count() == 0:
            return ""
        return locator.first.inner_text().strip()
    except Exception:
        return ""


def norm_text(s: str) -> str:
    s2 = (s or "").strip().lower()
    s2 = re.sub(r"\s+", " ", s2)
    s2 = re.sub(r"[^a-z0-9\s]", "", s2)  # drop punctuation
    return s2


def key_speaker_lab(speaker: str, lab: str) -> str:
    return f"{norm_text(speaker)} ({norm_text(lab)})"


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def best_fuzzy_match(target: str, candidates: Set[str]) -> Tuple[Optional[str], float]:
    best = None
    best_score = 0.0
    for c in candidates:
        sc = similarity(target, c)
        if sc > best_score:
            best = c
            best_score = sc
    return best, best_score


def parse_iso_date_from_event_link(href: str) -> Optional[str]:
    """Extract YYYY-MM-DD from URLs like ...-2026-01-14t140000"""
    if not href:
        return None
    m = re.search(r"(\d{4}-\d{2}-\d{2})t\d{4,6}", href)
    if m:
        return m.group(1)
    return None


def is_interest_group_seminar(title: str) -> bool:
    t = (title or "").strip().lower()
    if "crick lecture" in t:
        return False
    return t.startswith("interest group seminar") and ("| internal |" in t or "| external |" in t)


def extract_category_from_title(title: str) -> Optional[str]:
    t = (title or "").lower()
    if "| internal |" in t:
        return "Internal"
    if "| external |" in t:
        return "External"
    return None


def iso_to_uk(d: str) -> str:
    """YYYY-MM-DD -> dd/mm/yyyy"""
    try:
        dt = datetime.strptime(d, "%Y-%m-%d").date()
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return d


def format_friendly_dt(dt_obj: datetime) -> str:
    """Converts datetime to '9th Jan at 16:26'"""
    if not dt_obj:
        return "Unknown"

    day = dt_obj.day
    if 4 <= day <= 20 or 24 <= day <= 30:
        suffix = "th"
    else:
        suffix = ["st", "nd", "rd"][day % 10 - 1]

    return dt_obj.strftime(f"%-d{suffix} %b at %H:%M")


def get_next_update_countdown(last_updated_str: str) -> Dict[str, Any]:
    """Returns countdown info for the next 6-hour refresh cycle."""
    if not last_updated_str:
        return {"due": False, "target_epoch": None, "message": ""}

    try:
        clean_str = last_updated_str.replace("Z", "+00:00")
        last_up = datetime.fromisoformat(clean_str)

        now = datetime.now(timezone.utc)
        next_up = last_up + timedelta(hours=6)

        target_epoch = int(next_up.timestamp())
        due = next_up <= now

        if due:
            msg = "Spreadsheet update is due (scheduled > 6 hrs ago)."
        else:
            diff = next_up - now
            total_seconds = int(diff.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            if hours > 0:
                msg = f"Next update scheduled in {hours} hr {minutes} min."
            else:
                msg = f"Next update scheduled in {minutes} min."

        return {"due": due, "target_epoch": target_epoch, "message": msg}
    except Exception:
        return {"due": False, "target_epoch": None, "message": ""}


def get_next_update_message(last_updated_str: str) -> str:
    """Backwards-compatible message (used as fallback in the HTML)."""
    return str(get_next_update_countdown(last_updated_str).get("message", ""))


def display_item(item: Dict[str, str]) -> str:
    sp = (item.get("speaker") or "").strip()
    lab = (item.get("lab") or "").strip()
    if lab:
        return f"{sp} ({lab})"
    return sp


def html_escape(s: str) -> str:
    s = s or ""
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
         .replace("'", "&#39;")
    )


def today_iso() -> str:
    return datetime.now(LOCAL_TZ).date().isoformat()


def within_next_days(iso_d: str, days: int) -> bool:
    try:
        d = datetime.strptime(iso_d, "%Y-%m-%d").date()
        t = datetime.now(LOCAL_TZ).date()
        return t <= d <= (t + timedelta(days=days))
    except Exception:
        return False


def canonicalise_category_from_sheet(category: str) -> Optional[str]:
    c = (category or "").strip().lower()
    if c in {"internal"}:
        return "Internal"
    if c in {"external"}:
        return "External"
    if c in {"associate member", "associate-member", "associate"}:
        return "Internal"
    return None


def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def parse_iso_date(s: str) -> Optional[str]:
    s = (s or "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.date().isoformat()
    except Exception:
        return None


MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def extract_date_iso_from_text(text: str) -> Optional[str]:
    t = norm_space(text).lower()
    m = re.search(
        r"\b(\d{1,2})\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{4})\b",
        t,
    )
    if not m:
        return None
    day = int(m.group(1))
    month = MONTHS[m.group(2)]
    year = int(m.group(3))
    try:
        return datetime(year, month, day).date().isoformat()
    except Exception:
        return None


def external_fetch(
    session: requests.Session,
    url: str,
    params: Optional[Dict[str, str]] = None,
    timeout: int = 30,
) -> str:
    r = session.get(url, params=params, headers=EXTERNAL_HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.text


def external_listing_info(html: str) -> Dict[str, str]:
    """Returns a dict of { url: title_text } found on the listing page."""
    soup = BeautifulSoup(html, "html.parser")
    found: Dict[str, str] = {}

    # Keep the title and link paired by iterating the teaser blocks.
    for article in soup.select("article.c-teaser--event"):
        link_el = article.select_one("a.c-teaser__link")
        if not link_el:
            continue

        href = link_el.get("href")
        if not href:
            continue

        full_url = urljoin(EXTERNAL_BASE_URL, href)

        title_text = ""
        title_el = article.select_one(".c-teaser__title")
        if title_el:
            title_text = norm_space(title_el.get_text(" ", strip=True))

        found[full_url] = title_text

    return found


def external_has_next_page(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    return soup.select_one('a[rel="next"]') is not None


def external_extract_jsonld(html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    blocks = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        txt = (tag.string or "").strip()
        if not txt:
            continue
        try:
            data = json.loads(txt)
            if isinstance(data, list):
                blocks.extend([x for x in data if isinstance(x, dict)])
            elif isinstance(data, dict):
                blocks.append(data)
        except Exception:
            continue
    return blocks


def external_first_event_jsonld(blocks: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for b in blocks:
        t = b.get("@type")
        if t == "Event" or (isinstance(t, list) and "Event" in t):
            return b
    return None


def external_detail_page_text_description(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one("main") or soup
    return norm_space(main.get_text(" ", strip=True))


def external_parse_group_and_speaker_from_title(title: str) -> Tuple[str, str]:
    t = norm_space(title)
    if "|" in t:
        left, right = [norm_space(x) for x in t.split("|", 1)]
        left = re.sub(r"\s+Seminar\s*$", "", left, flags=re.IGNORECASE).strip()
        return left, right

    m = re.match(r"^(.*)\s+Seminar\s+(.*)$", t, flags=re.IGNORECASE)
    if m:
        return norm_space(m.group(1)), norm_space(m.group(2))
    return "", ""


def scrape_external_seminars() -> List[Dict[str, Any]]:
    session = requests.Session()

    all_listing_info: Dict[str, str] = {}
    page = 0
    while True:
        params = {
            "event_type": EXTERNAL_EVENT_TYPE_ID,
            "event_date": "All",
            "interest_group": "All",
            "page": str(page),
        }
        html = external_fetch(session, EXTERNAL_LISTING_URL, params=params)
        page_info = external_listing_info(html)
        if not page_info:
            break
        all_listing_info.update(page_info)
        if not external_has_next_page(html):
            break
        page += 1
        if page > 200:
            break
        time.sleep(0.1)

    seminars: List[Dict[str, Any]] = []
    for u, teaser_title in all_listing_info.items():
        try:
            html = external_fetch(session, u)
        except Exception:
            print(f"Failed to fetch {u}")
            continue
        blocks = external_extract_jsonld(html)
        ev = external_first_event_jsonld(blocks)

        date_iso = ""
        if ev:
            date_iso = parse_iso_date(str(ev.get("startDate", ""))) or ""
        if not date_iso:
            date_iso = extract_date_iso_from_text(html) or ""

        title = teaser_title
        if not title:
            if ev:
                title = norm_space(str(ev.get("name", "")))
            if not title:
                soup = BeautifulSoup(html, "html.parser")
                h1 = soup.select_one("h1")
                if h1:
                    title = norm_space(h1.get_text(" ", strip=True))

        desc = ""
        if ev:
            desc = norm_space(str(ev.get("description", "")))
        if not desc:
            desc = external_detail_page_text_description(html)

        group_label, speaker_name = external_parse_group_and_speaker_from_title(title)
        if not date_iso:
            continue

        seminars.append(
            {
                "title": title,
                "url": u,
                "date_iso": date_iso,
                "description": desc,
                "group_label": group_label,
                "speaker_name": speaker_name,
            }
        )
        time.sleep(0.1)

    return seminars


# ---------------------------
# Auth / SharePoint
# ---------------------------
def ensure_logged_in(page, interactive: bool) -> bool:
    page.goto(LOGIN_URL, wait_until="domcontentloaded")

    if page.locator(SSO_BUTTON).count() > 0:
        page.locator(SSO_BUTTON).first.click()

    try:
        page.wait_for_selector(PROFILE_BUTTON, timeout=10_000)
        return True
    except PWTimeoutError:
        if not interactive:
            return False

        print("Login not completed automatically.")
        print("Please finish Okta login in the opened browser window.")
        input("When you can see CrickNet and are logged in, press Enter here...")

        try:
            page.wait_for_selector(PROFILE_BUTTON, timeout=20_000)
            return True
        except PWTimeoutError:
            return False


def ensure_sharepoint_logged_in(page, interactive: bool) -> bool:
    target_site = SHAREPOINT_TRIGGER_FOLDER_URL
    page.goto(target_site, wait_until="domcontentloaded")
    url = page.url.lower()
    if "login.microsoftonline.com" in url or "_forms/default.aspx" in url or "login" in url:
        if not interactive:
            return False
        print("SharePoint login required.")
        print("Please complete the Microsoft/Crick sign-in in the opened browser window.")
        input("When you can see the SharePoint site, press Enter here...")
        page.goto(target_site, wait_until="domcontentloaded")
    return True


def get_sharepoint_request_digest(context) -> Optional[str]:
    contextinfo_url = (
        f"{SHAREPOINT_SITE}/sites/ScienceOperationsAdministration/_api/contextinfo"
    )
    try:
        resp = context.request.post(
            contextinfo_url,
            headers={"accept": "application/json;odata=verbose"},
        )
    except Exception:
        return None

    if not resp.ok:
        return None

    try:
        payload = resp.json()
    except Exception:
        return None

    return (
        payload.get("d", {})
        .get("GetContextWebInformation", {})
        .get("FormDigestValue")
    )


def download_sharepoint_json(context, page, interactive: bool) -> bool:
    if not ensure_sharepoint_logged_in(page, interactive=interactive):
        return False

    resp = context.request.get(
        SHAREPOINT_DOWNLOAD_URL,
        headers={"accept": "application/json"},
    )

    if not resp.ok:
        if not interactive:
            return False

        print(f"SharePoint download failed (HTTP {resp.status}).")
        print("If you were just prompted to sign in, finish that now and press Enter.")
        input("Press Enter to retry...")

        ensure_sharepoint_logged_in(page, interactive=True)
        resp = context.request.get(
            SHAREPOINT_DOWNLOAD_URL,
            headers={"accept": "application/json"},
        )

    if not resp.ok:
        return False

    content_bytes = resp.body()
    Path(LOCAL_JSON_PATH).write_bytes(content_bytes)
    return True


def close_extra_tabs(context, keep_page) -> None:
    for p in list(context.pages):
        if p != keep_page:
            try:
                p.close()
            except Exception:
                pass


# ---------------------------
# Scraping / Data shaping
# ---------------------------
def scrape_interest_group_events(page, events_url: str) -> List[Dict[str, Any]]:
    page.goto(events_url, wait_until="domcontentloaded")

    try:
        page.wait_for_selector(ROW_SELECTOR, timeout=10_000)
    except PWTimeoutError:
        return []

    rows = page.locator(ROW_SELECTOR)
    out: List[Dict[str, Any]] = []

    for i in range(rows.count()):
        row = rows.nth(i)

        title = safe_inner_text(row.locator(TITLE_SELECTOR))
        if not is_interest_group_seminar(title):
            continue

        href = ""
        try:
            if row.locator(LINK_SELECTOR).count() > 0:
                href = row.locator(LINK_SELECTOR).first.get_attribute("href") or ""
        except Exception:
            href = ""

        iso_date = parse_iso_date_from_event_link(href)
        category = extract_category_from_title(title)

        if not iso_date or not category:
            continue

        # Only today onwards
        if iso_date < today_iso():
            continue

        speakers: List[Tuple[str, str]] = []
        try:
            groups = row.locator(SPEAKER_GROUP_SELECTOR)
            for gi in range(groups.count()):
                g = groups.nth(gi)
                name = safe_inner_text(g.locator(SPEAKER_NAME_SELECTOR))

                labs = g.locator(SPEAKER_LAB_SELECTOR)
                lab_text = ""
                if labs.count() > 0:
                    lab_text = labs.last.inner_text().strip()

                if name:
                    speakers.append((name, lab_text))
        except Exception:
            pass

        out.append(
            {
                "date": iso_date,
                "title": title,
                "category": category,
                "href": href,
                "speakers": speakers,
            }
        )

    return out


def load_expected_from_json(path: str, group_name: str) -> Dict[Tuple[str, str], List[Dict[str, str]]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    records = raw.get("records", []) if isinstance(raw, dict) else raw

    out: Dict[Tuple[str, str], List[Dict[str, str]]] = {}
    t_iso = today_iso()

    for r in records:
        if not isinstance(r, dict):
            continue

        name = str(r.get("name", "")).strip()
        if name.lower() != group_name.lower():
            continue

        status = str(r.get("status", "")).strip().lower()
        if status != "confirmed":
            continue

        cat_raw = str(r.get("category", "")).strip()
        category = canonicalise_category_from_sheet(cat_raw)
        if category not in {"Internal", "External"}:
            continue

        d = str(r.get("date", "")).strip()
        if not d or d < t_iso:
            continue

        speaker = str(r.get("speaker_name", "")).strip()
        lab = str(r.get("lab_affiliation", "")).strip()
        if not speaker:
            continue

        item = {"key": key_speaker_lab(speaker, lab), "speaker": speaker, "lab": lab}
        out.setdefault((d, category), []).append(item)

    for k in out:
        out[k] = sorted(out[k], key=lambda x: (norm_text(x.get("speaker", "")), norm_text(x.get("lab", ""))))
    return out


def build_found_map(events: List[Dict[str, Any]]) -> Dict[Tuple[str, str], List[Dict[str, str]]]:
    out: Dict[Tuple[str, str], List[Dict[str, str]]] = {}
    t_iso = today_iso()

    for ev in events:
        d = str(ev.get("date", ""))
        cat = str(ev.get("category", ""))
        if not d or not cat:
            continue
        if d < t_iso:
            continue

        speakers = ev.get("speakers", [])
        items: List[Dict[str, str]] = []

        if isinstance(speakers, list):
            for pair in speakers:
                if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                    continue
                sp = str(pair[0]).strip()
                lab = str(pair[1]).strip()
                if not sp:
                    continue
                items.append({"key": key_speaker_lab(sp, lab), "speaker": sp, "lab": lab})

        out[(d, cat)] = sorted(items, key=lambda x: (norm_text(x.get("speaker", "")), norm_text(x.get("lab", ""))))

    return out


def build_external_found_by_group(
    seminars: List[Dict[str, Any]],
) -> Dict[str, Dict[str, List[Dict[str, str]]]]:
    label_to_json: Dict[str, str] = {}
    for g in GROUPS:
        json_name = str(g.get("json", "")).strip()
        label = JSON_TO_WEBSITE_GROUP.get(json_name, json_name)
        label_to_json[norm_text(label)] = json_name

    out: Dict[str, Dict[str, List[Dict[str, str]]]] = {}
    t_iso = today_iso()

    for s in seminars:
        d = str(s.get("date_iso", "")).strip()
        if not d or d < t_iso:
            continue
        group_label = str(s.get("group_label", "")).strip()
        speaker = str(s.get("speaker_name", "")).strip()
        if not group_label or not speaker:
            continue
        json_name = label_to_json.get(norm_text(group_label))
        if not json_name:
            continue
        item = {"key": key_speaker_lab(speaker, ""), "speaker": speaker, "lab": ""}
        out.setdefault(json_name, {}).setdefault(d, []).append(item)

    for g_map in out.values():
        for k in g_map:
            g_map[k] = sorted(g_map[k], key=lambda x: norm_text(x.get("speaker", "")))
    return out


# ---------------------------
# Cross-date speaker lookup
# ---------------------------
def build_global_speaker_lookup(
    found_map: Dict[Tuple[str, str], List[Dict[str, str]]]
) -> Dict[str, List[Dict[str, Any]]]:
    """Build a lookup of all speakers across all dates for cross-date matching.
    
    Returns a dict keyed by normalized speaker name, with list of entries containing
    date_iso, category, and original item data.
    """
    lookup: Dict[str, List[Dict[str, Any]]] = {}
    for (date_iso, category), items in found_map.items():
        for item in items:
            speaker_norm = norm_text(item.get("speaker", ""))
            if speaker_norm:
                if speaker_norm not in lookup:
                    lookup[speaker_norm] = []
                lookup[speaker_norm].append({
                    "date_iso": date_iso,
                    "category": category,
                    **item
                })
    return lookup


def build_external_website_lookup(
    seminars: List[Dict[str, Any]]
) -> Dict[str, List[Dict[str, Any]]]:
    """Build a lookup of external website seminars by normalized speaker name."""
    lookup: Dict[str, List[Dict[str, Any]]] = {}
    for s in seminars:
        speaker = str(s.get("speaker_name", "")).strip()
        speaker_norm = norm_text(speaker)
        if not speaker_norm:
            continue
        if speaker_norm not in lookup:
            lookup[speaker_norm] = []
        lookup[speaker_norm].append(s)
    return lookup


# ---------------------------
# Comparison model for report
# ---------------------------
def build_comparison_rows(
    expected_items: List[Dict[str, str]],
    found_items: List[Dict[str, str]],
    source_label: str = "CrickNet",
    current_date: str = "",
    cricknet_speaker_lookup: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    spreadsheet_speaker_lookup: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    external_website_lookup: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Build comparison rows between expected (spreadsheet) and found (CrickNet) items.
    
    Args:
        expected_items: Items from spreadsheet for this date
        found_items: Items from CrickNet for this date  
        source_label: Label for the source (e.g., "CrickNet")
        current_date: Current date being compared (ISO format)
        cricknet_speaker_lookup: All CrickNet speakers across all dates (for checking missing)
        spreadsheet_speaker_lookup: All spreadsheet speakers across all dates (for checking extras)
    """
    got_keys = {x["key"] for x in found_items if "key" in x}
    exp_keys = {x["key"] for x in expected_items if "key" in x}

    got_key_set: Set[str] = set(got_keys)
    consumed_got: Set[str] = set()

    rows: List[Dict[str, Any]] = []
    any_mismatch = False
    
    # Lists to collect detail info for summary
    date_mismatches_summary: List[Dict[str, Any]] = []
    truly_missing: List[str] = []
    truly_extra: List[str] = []

    def check_external(speaker_name: str) -> Optional[str]:
        if not external_website_lookup:
            return None
        norm_s = norm_text(speaker_name)
        if not norm_s:
            return None
        
        matches = external_website_lookup.get(norm_s)
        if not matches:
            return "Missing from external website"
        
        # Check if present on current date
        for m in matches:
            if m.get("date_iso") == current_date:
                return None # Present on correct date
        
        # Present but different date
        other_dates = sorted({m.get("date_iso", "") for m in matches if m.get("date_iso")})
        if other_dates:
             return f"On external website for {', '.join(other_dates)}"
        return "Missing from external website (no date)"

    # 1. Exact matches
    unmatched_expected = []
    for e in expected_items:
        e_key = e.get("key", "")
        e_disp = display_item(e)
        
        if e_key in got_key_set:
            note = f"Scheduled on {source_label}"
            ext_msg = check_external(e.get("speaker", ""))
            if ext_msg:
                note += f"; {ext_msg}"

            rows.append({
                "status": "ok",
                "icon": "✅",
                "expected": e_disp,
                "found": e_disp,
                "note": note,
                "score": None,
            })
            consumed_got.add(e_key)
        else:
            unmatched_expected.append(e)

    # 2. Fuzzy matches from remainders
    still_unmatched_expected = []
    for e in unmatched_expected:
        e_key = e.get("key", "")
        e_disp = display_item(e)
        candidates = [g for g in found_items if g.get("key") not in consumed_got]
        
        best, score = best_fuzzy_match(e_key, {g.get("key") for g in candidates if g.get("key")})
        used_speaker_fallback = False
        
        if not (best and score >= MIN_FUZZY_SCORE):
            # Try speaker-only match
            target_speaker = norm_text(e.get("speaker", ""))
            best = None
            score = 0.0
            for g in candidates:
                g_key = g.get("key", "")
                g_speaker = norm_text(g.get("speaker", ""))
                if not g_key or not g_speaker:
                    continue
                sc = similarity(target_speaker, g_speaker)
                if sc > score:
                    score = sc
                    best = g_key
            if best and score >= MIN_FUZZY_SCORE:
                used_speaker_fallback = True

        if best and score >= MIN_FUZZY_SCORE:
            best_disp = next((display_item(g) for g in found_items if g.get("key") == best), best)
            
            note = f"Closest match on {source_label}"
            status = "warn"
            icon = "⚠️"
            
            if used_speaker_fallback and score >= 1.0:
                 note = f"Scheduled on {source_label}"
                 status = "ok"
                 icon = "✅"
            elif used_speaker_fallback:
                 note = f"Closest match on {source_label} (speaker)"

            best_item = next((g for g in found_items if g.get("key") == best), {})
            ext_msg = check_external(best_item.get("speaker", ""))
            if ext_msg:
                note += f"; {ext_msg}"
                if status == "ok": # Downgrade OK if external issue? User said "flagged".
                    status = "warn"
                    icon = "⚠️"

            rows.append({
                "status": status,
                "icon": icon,
                "expected": e_disp,
                "found": best_disp,
                "note": note,
                "score": round(score * 100),
            })
            if status != "ok":
                any_mismatch = True
            consumed_got.add(best)
        else:
            still_unmatched_expected.append(e)

    # 3. Analyze leftovers for Date Mismatches
    
    # Remaining Expected items (potential missing or date mismatch)
    missing_analysis = []
    for e in still_unmatched_expected:
        e_disp = display_item(e)
        e_speaker_norm = norm_text(e.get("speaker", ""))
        
        found_on_other_date = None
        if cricknet_speaker_lookup and e_speaker_norm:
            other_entries = cricknet_speaker_lookup.get(e_speaker_norm, [])
            for entry in other_entries:
                if entry.get("date_iso") != current_date:
                    found_on_other_date = entry
                    break
        
        if found_on_other_date:
            other_date = found_on_other_date.get("date_iso", "")
            missing_analysis.append({
                "item": e,
                "disp": e_disp,
                "type": "date_mismatch",
                "other_date": other_date,
                "note": f"Scheduled on {other_date} on {source_label}"
            })
            date_mismatches_summary.append({
                "speaker": e_disp,
                "expected_date": current_date,
                "actual_date": other_date,
                "direction": "spreadsheet_to_cricknet"
            })
        else:
            missing_analysis.append({
                "item": e,
                "disp": e_disp,
                "type": "missing",
                "note": f"Not scheduled on {source_label}"
            })
            truly_missing.append(e_disp)

    # Remaining Found items (potential extra or date mismatch)
    extras = [g for g in found_items if g.get("key") not in consumed_got]
    extra_analysis = []
    for x in extras:
        x_disp = display_item(x)
        x_speaker_norm = norm_text(x.get("speaker", ""))
        
        found_on_spreadsheet_other_date = None
        if spreadsheet_speaker_lookup and x_speaker_norm:
            other_entries = spreadsheet_speaker_lookup.get(x_speaker_norm, [])
            for entry in other_entries:
                if entry.get("date_iso") != current_date:
                    found_on_spreadsheet_other_date = entry
                    break
        
        if found_on_spreadsheet_other_date:
            spreadsheet_date = found_on_spreadsheet_other_date.get("date_iso", "")
            extra_analysis.append({
                "item": x,
                "disp": x_disp,
                "type": "date_mismatch",
                "other_date": spreadsheet_date,
                "note": f"Expected on {spreadsheet_date} per spreadsheet"
            })
            date_mismatches_summary.append({
                "speaker": x_disp,
                "expected_date": spreadsheet_date,
                "actual_date": current_date,
                "direction": "cricknet_to_spreadsheet"
            })
        else:
            extra_analysis.append({
                "item": x,
                "disp": x_disp,
                "type": "extra",
                "note": ""
            })
            truly_extra.append(x_disp)

    # 4. Pair up and create rows
    # We zip the lists. If one is longer, we handle leftovers.
    import itertools
    for m, x in itertools.zip_longest(missing_analysis, extra_analysis):
        any_mismatch = True
        
        # Prepare row data
        e_disp = m["disp"] if m else "(extra on CrickNet)"
        f_disp = x["disp"] if x else "(none)"
        
        # Determine status and note
        status = "bad" # default
        icon = "❌"
        note_parts = []
        
        is_date_mismatch = False
        
        if m:
            if m["type"] == "date_mismatch":
                is_date_mismatch = True
                note_parts.append("Date mismatch")
            elif m["type"] == "missing":
                pass # Status bad
        
        if x:
            if x["type"] == "date_mismatch":
                is_date_mismatch = True
                if "Date mismatch" not in note_parts:
                    note_parts.append("Date mismatch")
            
            # Check external consistency for the Found item
            ext_msg = check_external(x["item"].get("speaker", ""))
            if ext_msg:
                note_parts.append(ext_msg)
            
            elif x["type"] == "extra":
                if not m:
                    status = "extra"
                    icon = "➕"
        
        if is_date_mismatch:
            status = "date_mismatch" # Maps to Check
            icon = "📅"
        elif m and not x:
             status = "bad"
             icon = "❌"
             note_parts.append(m["note"])
        elif x and not m:
             status = "extra"
             icon = "➕"
        elif m and x:
             # Paired Missing + Extra (checking slot mismatch)
             # If neither is officially a date mismatch, treat as a generic mismatch/warn
             if not is_date_mismatch:
                 status = "warn"
                 icon = "⚠️"
                 note_parts.append(f"Mismatch on {source_label}")

        # Improve note for combined row
        # If we have both, combine notes?
        # User wants "Found: Sunaina" (Extra) next to "Expected: Giampietro" (Missing)
        
        rows.append({
            "status": status,
            "icon": icon,
            "expected": m["disp"] if m else "", # Empty string or explicit label? User screenshot shows blank expected for extra
            "found": x["disp"] if x else "",
            "note": "; ".join(note_parts) if note_parts else "",
            "score": None
        })



    likely_pairs: List[Dict[str, Any]] = []
    # Only show likely pairs if there are true missing/extras (not date mismatches)
    if len(truly_missing) == 1 and len(truly_extra) == 1:
        m = truly_missing[0]
        e = truly_extra[0]
        sc = similarity(m, e)
        likely_pairs.append({"a": m, "b": e, "score": round(sc * 100)})

    summary = {
        "any_mismatch": any_mismatch,
        "missing_exact": truly_missing, 
        "date_mismatches": date_mismatches_summary,
        "extras_exact": truly_extra,
        "likely_pairs": likely_pairs,
    }
    return rows, summary


def build_report_model() -> Dict[str, Any]:
    now_dt = datetime.now(LOCAL_TZ)
    model: Dict[str, Any] = {
        "generatedAt": now_dt.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "generated_friendly": format_friendly_dt(now_dt),
        "reportDateIso": now_dt.date().isoformat(),
        "sourceLastUpdated": "",
        "sourceLastUpdatedRaw": "",
        "sourceLastUpdatedFriendly": "",
        "nextUpdateMsg": "",
        "nextUpdateDue": False,
        "nextUpdateTargetEpoch": None,
        "recordCount": None,
        "groups": [],
        "priority": [],
    }

    if Path(LOCAL_JSON_PATH).exists():
        try:
            raw = json.loads(Path(LOCAL_JSON_PATH).read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                lu_str = str(raw.get("lastUpdated", "")).strip()
                model["sourceLastUpdated"] = lu_str
                model["sourceLastUpdatedRaw"] = lu_str
                recs = raw.get("records", [])
                if isinstance(recs, list):
                    model["recordCount"] = len(recs)
                if lu_str:
                    try:
                        lu_dt = datetime.fromisoformat(lu_str.replace("Z", "+00:00")).astimezone(LOCAL_TZ)
                        model["sourceLastUpdatedFriendly"] = format_friendly_dt(lu_dt)
                    except Exception:
                        model["sourceLastUpdatedFriendly"] = lu_str
                cd = get_next_update_countdown(lu_str)
                model["nextUpdateMsg"] = str(cd.get("message", ""))
                model["nextUpdateDue"] = bool(cd.get("due", False))
                model["nextUpdateTargetEpoch"] = cd.get("target_epoch")
        except Exception:
            pass

    for g in GROUPS:
        display_name = str(g["display"]).strip()
        json_name = str(g["json"]).strip()
        events_url = str(g["url"]).strip()

        model["groups"].append({
            "display": display_name,
            "json": json_name,
            "url": events_url,
            "sections": [],
        })

    return model


# ---------------------------
# HTML Report
# ---------------------------
def generate_mailto(group_name: str, missing_list: List[str], date_str: str) -> str:
    """Creates a pre-filled mailto link for quick emailing."""
    speakers = ", ".join(missing_list)
    subject = f"Missing Seminar: {speakers} - {date_str}"
    body = (
        f"Hi,\n\n"
        f"Please schedule the following speakers for the {group_name} seminar on {date_str}:\n"
        f"{speakers}\n\n"
        f"Thanks."
    )
    
    # Safe encoding
    params = {
        "cc": EMAIL_CONFIG["cc"],
        "subject": subject,
        "body": body
    }
    query = "&".join(f"{k}={quote(v)}" for k, v in params.items())
    return f"mailto:{EMAIL_CONFIG['to']}?{query}"


def render_report_html(report: Dict[str, Any]) -> str:
    generated_friendly = html_escape(str(report.get("generated_friendly", "")))
    source_updated_friendly = html_escape(str(report.get("sourceLastUpdatedFriendly", "")))
    report_date_iso_raw = str(report.get("reportDateIso", "")).strip()
    if not report_date_iso_raw:
        report_date_iso_raw = today_iso()
    report_date_iso = html_escape(report_date_iso_raw)
    # Countdown: render DaisyUI markup (do NOT html_escape this block)
    next_update_msg_fallback = html_escape(str(report.get("nextUpdateMsg", "")))
    next_due = bool(report.get("nextUpdateDue", False))
    next_target = report.get("nextUpdateTargetEpoch")

    if next_due or not next_target:
        next_update_html = next_update_msg_fallback
    else:
        next_update_html = f"""
          <span class=\"mr-2\">Next update in</span>
          <span id=\"next-update-countdown\" data-target-epoch=\"{int(next_target)}\">
            <span class=\"countdown font-mono\"><span id=\"cd-hours\" style=\"--value:0;\" aria-live=\"polite\" aria-label=\"0\">0</span></span>h
            <span class=\"countdown font-mono ml-2\"><span id=\"cd-mins\" style=\"--value:0;\" aria-live=\"polite\" aria-label=\"0\">0</span></span>m
            <span class=\"countdown font-mono ml-2\"><span id=\"cd-secs\" style=\"--value:0;\" aria-live=\"polite\" aria-label=\"0\">0</span></span>s
          </span>
        """
    if not generated_friendly:
        generated_friendly = html_escape(str(report.get("generatedAt", "")))
    if not source_updated_friendly:
        source_updated_friendly = html_escape(str(report.get("sourceLastUpdated", "")))
    if not source_updated_friendly:
        source_updated_friendly = "Unknown"

    priority = report.get("priority", [])
    groups = report.get("groups", [])

    def group_slug(name: str) -> str:
        s = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower())
        return s.strip("-") or "group"

    def section_anchor(group_name: str, date_iso: str, category: str) -> str:
        g_slug = group_slug(group_name)
        d = re.sub(r"[^0-9]+", "-", (date_iso or "").strip()).strip("-") or "date"
        c_slug = group_slug(category)
        return f"section-{g_slug}-{d}-{c_slug}"

    priority_groups = {p.get("group", "") for p in priority if p.get("group")}
    priority_group_count = len(priority_groups)
    priority_item_count = len(priority)
    priority_counts: Dict[str, int] = {}
    priority_counts_int: Dict[str, int] = {}
    priority_counts_ext: Dict[str, int] = {}
    priority_display: Dict[str, str] = {}

    for g in groups:
        slug = group_slug(g.get("display", ""))
        priority_counts[slug] = 0
        priority_counts_int[slug] = 0
        priority_counts_ext[slug] = 0
        priority_display[slug] = str(g.get("display", "")).strip()

    for p in priority:
        slug = group_slug(p.get("group", ""))
        priority_counts[slug] = priority_counts.get(slug, 0) + 1

        cat = str(p.get("category", "")).strip().lower()
        if "external" in cat:
            priority_counts_ext[slug] = priority_counts_ext.get(slug, 0) + 1
        else:
            # Treat anything not explicitly external as internal
            priority_counts_int[slug] = priority_counts_int.get(slug, 0) + 1

        if slug not in priority_display:
            priority_display[slug] = str(p.get("group", "")).strip()

    priority_summary_items = "\n".join(
        f'''
        <div class="priority-count group-{slug}">
          <span class="label">{html_escape(priority_display.get(slug, slug))}</span>
          <div class="dropdown dropdown-hover dropdown-end">
            <div tabindex="0" role="button" class="value">{priority_counts.get(slug, 0)}</div>
            <ul tabindex="-1" class="dropdown-content menu bg-base-100 rounded-box z-10 w-40 p-2 shadow-sm">
              <li><a>Internal {priority_counts_int.get(slug, 0)}</a></li>
              <li><a>External {priority_counts_ext.get(slug, 0)}</a></li>
            </ul>
          </div>
        </div>
        '''
        for slug in priority_display
    )

    group_filter_options = "\n".join(
        f'<option value="{group_slug(g.get("display", ""))}">{html_escape(g.get("display", ""))}</option>'
        for g in groups
    )

    def get_badge_counts_by_category(sections: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
        """
        Returns a dict of status -> {total, int, ext}
        Statuses: confirmed, ok, missing, check.
        Logic mostly mirroring count_statuses but split by category.
        """
        stats = {
            "confirmed": {"total": 0, "int": 0, "ext": 0},
            "ok":        {"total": 0, "int": 0, "ext": 0},
            "missing":   {"total": 0, "int": 0, "ext": 0},
            "check":     {"total": 0, "int": 0, "ext": 0},
        }

        for s in sections:
            cat_raw = str(s.get("category", "")).lower()
            is_ext = ("external" in cat_raw) # covers "External" and "External website"
            
            for r in s.get("rows", []):
                st = r.get("status")
                
                # Logic:
                # OK -> OK + Confirmed
                # Warn -> Check + Confirmed
                # Bad -> Missing + Confirmed
                # Extra -> Check (but NOT confirmed)

                if st == "ok":
                    stats["ok"]["total"] += 1
                    stats["confirmed"]["total"] += 1
                    if is_ext:
                        stats["ok"]["ext"] += 1
                        stats["confirmed"]["ext"] += 1
                    else:
                        stats["ok"]["int"] += 1
                        stats["confirmed"]["int"] += 1

                elif st == "warn":
                    stats["check"]["total"] += 1
                    stats["confirmed"]["total"] += 1
                    if is_ext:
                        stats["check"]["ext"] += 1
                        stats["confirmed"]["ext"] += 1
                    else:
                        stats["check"]["int"] += 1
                        stats["confirmed"]["int"] += 1

                elif st == "bad":
                    stats["missing"]["total"] += 1
                    stats["confirmed"]["total"] += 1
                    if is_ext:
                        stats["missing"]["ext"] += 1
                        stats["confirmed"]["ext"] += 1
                    else:
                        stats["missing"]["int"] += 1
                        stats["confirmed"]["int"] += 1

                elif st == "extra":
                    stats["check"]["total"] += 1
                    if is_ext:
                        stats["check"]["ext"] += 1
                    else:
                        stats["check"]["int"] += 1
        return stats

    def make_tooltip(counts: Dict[str, int]) -> str:
        return f"Int: {counts['int']} | Ext: {counts['ext']}"

    all_sections = []
    for g in groups:
        all_sections.extend(g.get("sections", []))
    
    # Overall summary counts (we use the same logic just for totals)
    global_stats = get_badge_counts_by_category(all_sections)

    total_confirmed = global_stats["confirmed"]["total"]
    total_ok = global_stats["ok"]["total"]
    total_missing = global_stats["missing"]["total"]
    total_check = global_stats["check"]["total"]

    summary_line = (
        f"{total_confirmed} confirmed, "
        f"{total_ok} OK, "
        f"{total_missing} missing on listings, "
        f"{total_check} check."
    )

    def badge(status: str) -> str:
        if status == "ok":
            return "badge badge-success"
        if status == "warn":
            return "badge badge-warning"
        if status == "bad":
            return "badge badge-error"
        if status == "date_mismatch":
            return "badge badge-warning"  # Amber/orange for date mismatch
        return "badge"

    def status_label(status: str) -> str:
        return {"ok": "OK", "warn": "Check", "bad": "Missing", "extra": "Extra", "date_mismatch": "Check"}.get(status, status)

    group_palette = {
        "cancer": "var(--col-blue)",
        "development-and-stem-cells": "var(--col-taupe)",
        "genes-to-cells": "var(--col-clay)",
        "immunology": "var(--col-bronze)",
        "host-and-pathogen": "var(--col-sand)",
        "neuroscience": "var(--col-blue)",
        "structural-chemical-biology": "var(--col-taupe)",
    }
    group_color_css = []
    for slug, color in group_palette.items():
        group_color_css.append(f".group-{slug} {{ --group-color: {color}; }}")
    group_color_css_text = "\n".join(group_color_css)

    def ticket_date_parts(iso: str, uk: str) -> Tuple[str, str]:
        if iso:
            try:
                dt = datetime.strptime(iso, "%Y-%m-%d")
                return dt.strftime("%-d"), dt.strftime("%b")
            except Exception:
                pass
        if uk:
            try:
                dt = datetime.strptime(uk, "%d/%m/%Y")
                return dt.strftime("%-d"), dt.strftime("%b")
            except Exception:
                pass
        return "", ""
        
    def date_cell_parts(iso: str, uk: str) -> str:
        d_str, w_str = "", ""
        if iso:
            try:
                dt = datetime.strptime(iso, "%Y-%m-%d")
                d_str = dt.strftime("%-d %b")
                w_str = dt.strftime("%a")
                return f'<div class="font-bold text-base leading-tight">{d_str}</div><div class="text-xs opacity-70 uppercase tracking-wide">{w_str}</div>'
            except: pass
        return f'<div class="font-bold text-base">{uk}</div>'

    def short_group_label(name: str) -> str:
        parts = (name or "").strip().split()
        if not parts:
            return "Group"
        return parts[0][:4]

    calendar_events: List[Dict[str, str]] = []
    for g in groups:
        g_name = str(g.get("display", "")).strip()
        if not g_name:
            continue
        slug = group_slug(g_name)
        short_label = short_group_label(g_name)
        for s in g.get("sections", []):
            date_iso = str(s.get("date_iso", "")).strip()
            if not date_iso:
                continue
            category_raw = str(s.get("category", "")).strip()
            anchor = section_anchor(g_name, date_iso, category_raw)
            calendar_events.append({
                "date_iso": date_iso,
                "group_slug": slug,
                "group_label": g_name,
                "category": category_raw,
                "anchor": anchor,
                "short_label": short_label,
            })

    calendar_events_json = json.dumps(calendar_events).replace("</", "<\\/")
    calendar_pills_parts = []
    for ev in calendar_events:
        cat = str(ev.get("category", "")).lower()
        border_class = "border-dashed" if "external" in cat else "border-solid"
        calendar_pills_parts.append(f"""
        <a href="#{html_escape(ev.get("anchor", ""))}" class="cal-pill group-{html_escape(ev.get("group_slug", ""))} {border_class} is-hidden" data-cal-date="{html_escape(ev.get("date_iso", ""))}" title="{html_escape(ev.get("group_label", ""))}">
            <span class="cal-dot group-{html_escape(ev.get("group_slug", ""))}"></span>
            <span class="cal-text">{html_escape(ev.get("short_label", ""))}</span>
        </a>
        """)
    calendar_pills_html = "\n".join(calendar_pills_parts)

    # Priority cards
    priority_cards = ""
    if priority:
        cards = []
        for idx, p in enumerate(priority):
            p_slug = group_slug(p.get("group", ""))
            anchor = section_anchor(p.get("group", ""), p.get("date_iso", ""), p.get("category", ""))
            day, month = ticket_date_parts(p.get("date_iso"), p.get("date_uk"))
            missing_list = [str(x) for x in p.get("missing", []) if str(x).strip()]
            missing_text = ", ".join(missing_list) if missing_list else "Unknown"
            
            mailto_link = generate_mailto(p.get("group", ""), missing_list, p.get("date_uk", ""))
            
            cards.append(f"""
              <div class="priority-ticket reveal group-{p_slug}" style="animation-delay: {idx * 60}ms;">
                <div class="ticket-sidebar" style="background-color: var(--group-color, var(--col-blue));">
                  <div class="ticket-date">
                    <span class="day">{html_escape(day)}</span>
                    <span class="month">{html_escape(month)}</span>
                  </div>
                </div>
                <div class="ticket-content flex flex-col justify-between">
                  <div>
                    <div class="ticket-header">
                      <span class="badge badge-outline">{html_escape(p["group"])}</span>
                      <span class="ticket-type">{html_escape(p["category"])}</span>
                    </div>
                    <div class="ticket-title"><a href="#{html_escape(anchor)}" class="hover:underline">{html_escape(p["title"])}</a></div>
                    <div class="ticket-missing">
                      <strong>Missing:</strong> {html_escape(missing_text)}
                    </div>
                  </div>
                  <div class="mt-3 flex gap-2">
                    <a href="{html_escape(p["url"])}" target="_blank" class="btn btn-xs btn-outline">View Page</a>
                    <a href="{html_escape(mailto_link)}" class="btn btn-xs btn-outline">Draft Email</a>
                  </div>
                </div>
              </div>
            """)
        priority_cards = "\n".join(cards)
    else:
        priority_cards = """
          <div class="alert alert-success">
            <span>Nothing urgent: no missing Internal/External seminars in the next 14 days.</span>
          </div>
        """

    # Group sections
    group_html_parts = []
    group_nav_items = []
    for idx, g in enumerate(groups):
        g_name = html_escape(g.get("display", ""))
        g_url = html_escape(g.get("url", ""))
        slug = group_slug(g.get("display", ""))
        sections = g.get("sections", [])

        # Detailed Counts with Tooltips
        stats = get_badge_counts_by_category(sections)
        
        confirmed_count = stats["confirmed"]["total"]
        ok_count = stats["ok"]["total"]
        missing_count = stats["missing"]["total"]
        check_count = stats["check"]["total"]
        
        has_issues = missing_count > 0 or check_count > 0

        group_nav_items.append(f"""
          <li class="group-{slug}" data-has-issues="{str(has_issues).lower()}">
            <a class="group-link group-{slug}" href="#group-{slug}" data-group-link="{slug}">
              <span class="name">{g_name}</span>
              <span class="group-badges text-xs">
                <span class="badge badge-ghost">{confirmed_count}</span>
                <span class="badge badge-success">{ok_count}</span>
                <span class="badge badge-error">{missing_count}</span>
                <span class="badge badge-warning">{check_count}</span>
              </span>
            </a>
          </li>
        """)

        group_html_parts.append(f"""
          <div id="group-{slug}" data-group="{slug}" data-has-issues="{str(has_issues).lower()}" class="card bg-base-100 shadow group-card group-{slug} reveal" style="animation-delay: {idx * 70}ms;">
            <div class="card-body p-0">
              <details class="group-details collapse" open>
                <summary class="collapse-title px-6 py-5 cursor-pointer">
                  <div class="flex flex-wrap items-center justify-between gap-y-3 gap-x-4 w-full pr-8 relative">
                    
                    <!-- Left: Title & Link -->
                    <div class="flex flex-wrap items-center gap-3">
                        <h2 class="card-title m-0 text-lg sm:text-xl">{g_name}</h2>
                        <a class="btn btn-xs btn-outline shrink-0" href="{g_url}" target="_blank" rel="noopener">Open events page</a>
                    </div>
                    
                    <!-- Right: Badges -->
                    <div class="flex flex-wrap items-center gap-2 justify-end">
                         <!-- Group 1: Good stuff -->
                         <div class="flex items-center gap-2">
                            <div class="tooltip tooltip-bottom" data-tip="{make_tooltip(stats['confirmed'])}">
                                <span class="badge badge-neutral shrink-0">{confirmed_count} confirmed</span>
                            </div>
                            <div class="tooltip tooltip-bottom" data-tip="{make_tooltip(stats['ok'])}">
                                <span class="badge badge-success shrink-0">{ok_count} OK</span>
                            </div>
                         </div>
                         <!-- Group 2: Bad stuff -->
                         <div class="flex items-center gap-2">
                            <div class="tooltip tooltip-bottom" data-tip="{make_tooltip(stats['missing'])}">
                                <span class="badge badge-error shrink-0">{missing_count} missing</span>
                            </div>
                            <div class="tooltip tooltip-bottom" data-tip="{make_tooltip(stats['check'])}">
                                <span class="badge badge-warning shrink-0">{check_count} check</span>
                            </div>
                         </div>
                    </div>

                    <!-- Chevron (Absolute right) -->
                    <div class="absolute right-0 top-1/2 -translate-y-1/2">
                        <svg class="w-5 h-5 transition-transform duration-300 transform chevron" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                           <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                        </svg>
                    </div>

                  </div>
                </summary>

                <div class="collapse-content px-6 pb-6">
                  <div class="mt-2 space-y-4">
        """)

        if not sections:
            group_html_parts.append("""
                <div class="alert">
                  <span>No upcoming Internal/External seminars found (or no data available).</span>
                </div>
            """)
        elif missing_count == 0 and check_count == 0:
             group_html_parts.append("""
                <div class="flex flex-col items-center justify-center p-8 text-center opacity-60">
                   <div class="text-4xl mb-2">✅</div>
                   <div class="text-lg font-medium">All Good</div>
                   <div class="text-sm">Everything scheduled matches the spreadsheet.</div>
                </div>
            """)
        else:
            for s in sections:
                date_uk = html_escape(s.get("date_uk", ""))
                date_iso = s.get("date_iso", "")
                category_raw = s.get("category", "")
                category = html_escape(category_raw)
                title = html_escape(s.get("title", "Interest group seminar"))
                source_label = html_escape(str(s.get("source_label", "CrickNet")))
                found_label = "Found"
                any_mismatch = bool(s.get("any_mismatch"))
                rows_list = s.get("rows", [])
                has_missing = any(r.get("status") == "bad" for r in rows_list)
                has_check = any(r.get("status") in {"warn", "extra", "date_mismatch"} for r in rows_list)
                box_class = "border border-base-200 rounded-xl p-4 bg-base-100 shadow-sm"
                
                # Header Badge Logic
                if has_missing:
                    header_badge = "badge-error"
                    header_text = "Missing"
                elif has_check:
                    header_badge = "badge-warning"
                    header_text = "Check"
                else:
                    header_badge = "badge-success"
                    header_text = "All good"

                # Table rows
                tr_parts = []
                for r in rows_list:
                    st = r.get("status", "")
                    tr_parts.append(f"""
                      <tr data-status="{html_escape(st)}">
                        <td class="w-28">
                          <span class="{badge(st)}">{html_escape(status_label(st))}</span>
                        </td>
                        <td class="align-top break-words">{html_escape(r.get("expected",""))}</td>
                        <td class="align-top break-words">{html_escape(r.get("found",""))}</td>
                        <td class="align-top break-words">
                          {html_escape(r.get("note",""))}
                          {f' ({int(r["score"])}% similar)' if r.get("score") is not None else ''}
                        </td>
                      </tr>
                    """)

                missing_list = s.get("missing", [])
                date_mismatches_list = s.get("date_mismatches", [])
                extra_list = s.get("extras", [])
                likely = s.get("likely_pairs", [])

                detail_parts = []
                if any_mismatch:
                    if missing_list:
                        mailto_missing = generate_mailto(g_name, missing_list, date_uk)
                        detail_parts.append(f"""
                          <div class="mt-3 detail-block p-3 bg-red-50 rounded-lg border border-red-100" data-detail="missing">
                            <div class="flex justify-between items-start">
                                <div>
                                    <div class="font-semibold text-red-800 text-sm">Found on spreadsheet, missing on {source_label}:</div>
                                    <ul class="list-disc ml-6 text-sm text-red-900 mt-1">
                                    {''.join(f"<li>{html_escape(x)}</li>" for x in missing_list)}
                                    </ul>
                                </div>
                                <a href="{html_escape(mailto_missing)}" class="btn btn-xs btn-outline btn-error bg-white">Draft Email</a>
                            </div>
                          </div>
                        """)
                    if date_mismatches_list:
                        # Build different messages based on mismatch direction
                        dm_lines = []
                        for dm in date_mismatches_list:
                            speaker = html_escape(dm.get('speaker', ''))
                            direction = dm.get('direction', '')
                            if direction == 'cricknet_to_spreadsheet':
                                # Speaker appears on CrickNet for this date, but spreadsheet says different date
                                spreadsheet_date = dm.get('expected_date', '')
                                dm_lines.append(f"<li>{speaker} is scheduled for <strong>{html_escape(spreadsheet_date)}</strong> on spreadsheet, but appears here on {source_label}</li>")
                            else:
                                # Speaker on spreadsheet for this date, but CrickNet shows different date  
                                cricknet_date = dm.get('actual_date', '')
                                dm_lines.append(f"<li>{speaker} is on the spreadsheet for this date, but scheduled for <strong>{html_escape(cricknet_date)}</strong> on {source_label}</li>")
                        
                        detail_parts.append(f"""
                          <div class="mt-3 detail-block p-3 bg-amber-50 rounded-lg border border-amber-200" data-detail="date-mismatch">
                            <div class="font-semibold text-amber-800 text-sm">📅 Date mismatch:</div>
                            <ul class="list-disc ml-6 text-sm text-amber-900 mt-1">
                              {''.join(dm_lines)}
                            </ul>
                          </div>
                        """)
                    if extra_list:
                        detail_parts.append(f"""
                          <div class="mt-3 detail-block p-3 bg-gray-50 rounded-lg border border-gray-100" data-detail="extra">
                            <div class="font-semibold text-gray-700 text-sm">Found on {source_label}, not on spreadsheet:</div>
                            <ul class="list-disc ml-6 text-sm text-gray-800 mt-1">
                              {''.join(f"<li>{html_escape(x)}</li>" for x in extra_list)}
                            </ul>
                          </div>
                        """)
                    if likely:
                        detail_parts.append(f"""
                          <div class="mt-3 detail-block p-3 bg-orange-50 rounded-lg border border-orange-100" data-detail="likely">
                            <div class="font-semibold text-orange-800 text-sm">Likely match:</div>
                            <ul class="list-disc ml-6 text-sm text-orange-900 mt-1">
                              {''.join(f"<li>{html_escape(x['a'])} &nbsp;↔&nbsp; {html_escape(x['b'])} ({int(x['score'])}% similar)</li>" for x in likely)}
                            </ul>
                          </div>
                        """)

                group_html_parts.append(f"""
                  <div id="{html_escape(section_anchor(g.get("display", ""), s.get("date_iso", ""), s.get("category", "")))}" class="{box_class} date-card" data-group="{slug}" data-category="{html_escape(category_raw).lower()}" data-date="{html_escape(date_iso)}" data-group-label="{html_escape(g_name)}" data-group-url="{html_escape(g_url)}">
                    <div class="flex flex-row items-start gap-4 mb-3">
                      <div class="flex-none w-16 text-center pt-1">
                         {date_cell_parts(date_iso, date_uk)}
                      </div>
                      <div class="flex-1 min-w-0">
                         <div class="flex items-center gap-2 mb-1">
                            <span class="badge {header_badge}">{header_text}</span>
                            <span class="text-xs uppercase tracking-wide text-gray-500 font-bold">{category}</span>
                         </div>
                         <div class="text-sm font-medium">{title}</div>
                      </div>
                    </div>

                    <div class="overflow-x-auto">
                      <table class="table table-sm">
                        <thead>
                          <tr>
                            <th>Status</th>
                            <th>Expected</th>
                            <th>{found_label}</th>
                            <th>Note</th>
                          </tr>
                        </thead>
                        <tbody>
                          {''.join(tr_parts)}
                        </tbody>
                      </table>
                    </div>

                    {''.join(detail_parts)}
                  </div>
                """)

        group_html_parts.append("""
                  </div>
                </div>
              </details>
            </div>
          </div>
        """)

    group_html = "\n".join(group_html_parts)
    group_nav_html = "\n".join(group_nav_items)

    html = f"""<!doctype html>
<html lang="en" data-theme="light">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Crick Seminar Checker Report</title>

  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Spectral:wght@400;500;600&display=swap" rel="stylesheet" />

  <!-- Tailwind + DaisyUI CDN -->
  <link href="https://cdn.jsdelivr.net/npm/daisyui@4.12.14/dist/full.min.css" rel="stylesheet" type="text/css" />
  <script src="https://cdn.tailwindcss.com"></script>

  <!-- AlpineJS CDN -->
  <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>

  <style>
    :root {{
      /* Requested Palette */
      --col-blue: #628395;
      --col-taupe: #96897b;
      --col-clay: #dbad6a;
      --col-bronze: #cf995f;
      --col-sand: #d0ce7c;

      --page-bg: #f8f9fa;
      --card-bg: #ffffff;
      --text-main: #2d3748;
      --text-muted: #718096;
      --group-color: var(--col-blue);
    }}

    html {{
      scroll-behavior: smooth;
    }}

    body {{
      font-family: "Spectral", serif;
      background: radial-gradient(circle at top left, #f2efe6 0%, #f7f4ec 45%, #eef4f7 100%);
      color: var(--text-main);
    }}

    h1, h2, h3, .stat-value {{
      font-family: "Space Grotesk", sans-serif;
      color: var(--text-main);
      letter-spacing: -0.01em;
    }}

    aside, .btn, .badge, .stat-value, table, .input, .select, .tooltip {{
      font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    }}

    .group-card {{
      border-left: 6px solid var(--group-color);
      background: linear-gradient(90deg, color-mix(in srgb, var(--group-color) 12%, #ffffff) 0%, #ffffff 55%);
      scroll-margin-top: 5.5rem;
    }}

    .group-card:target {{
      box-shadow: 0 0 0 2px color-mix(in srgb, var(--group-color) 25%, transparent);
    }}

    .group-link {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 240px;
      align-items: center;
      gap: 0.75rem;
      padding: 0.65rem 0.85rem 0.65rem 1.7rem;
      border-left: 4px solid var(--group-color);
      background: linear-gradient(90deg, #fff 0%, #fcfcfc 100%);
      color: var(--text-main);
      border-radius: 0.75rem;
      transition: background 200ms ease, transform 200ms ease, box-shadow 200ms ease;
    }}

    .group-link::before {{
      content: "";
      position: absolute;
      width: 0.55rem;
      height: 0.55rem;
      border-radius: 9999px;
      background: var(--group-color);
      left: 0.65rem;
      top: 50%;
      transform: translateY(-50%);
    }}

    .group-link {{
      position: relative;
    }}

    .group-link .name {{
      font-weight: 600;
      line-height: 1.2;
      white-space: normal;
    }}

    .group-link.is-active {{
      background: color-mix(in srgb, var(--group-color) 15%, white);
      font-weight: 600;
      border-left-width: 6px;
    }}

    .group-link.is-active::before {{
      transform: translateY(-50%) scale(1.2);
    }}

    .group-badges {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0.35rem 0.4rem;
      justify-items: stretch;
    }}

      .group-badges .badge {{
        width: 100%;
        justify-content: center;
        white-space: nowrap;
      }}

      /* (dropdown wrappers in group badges styles removed) */

    .quick-summary {{
      display: none;
      opacity: 0;
      transform: translateY(-6px);
      pointer-events: none;
    }}

    .quick-summary.is-visible {{
      display: block;
      opacity: 1;
      transform: translateY(0);
      pointer-events: auto;
      animation: quickFade 220ms ease;
    }}

    .interest-groups-card {{
      position: sticky;
      top: 4.5rem;
      max-height: calc(100vh - 5rem);
      overflow: auto;
    }}

    .summary-stats {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
      gap: 0.75rem;
      width: 100%;
    }}

    .summary-stat {{
      background: var(--card-bg);
      border: 1px solid #e2e8f0;
      border-radius: 0.9rem;
      padding: 0.75rem 1rem;
    }}

    .summary-stat .label {{
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--text-muted);
    }}

    .summary-stat .value {{
      font-family: "Space Grotesk", sans-serif;
      font-size: 1.6rem;
      font-weight: 600;
      margin-top: 0.2rem;
    }}

    .summary-stat.value-ok .value {{
      color: #16a34a;
    }}

    .summary-stat.value-missing .value {{
      color: #dc2626;
    }}

    .summary-stat.value-check .value {{
      color: #d97706;
    }}

    .priority-counts {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 0.5rem;
      margin-top: 0.75rem;
    }}

    .priority-count {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0.45rem 0.75rem;
      border-radius: 0.7rem;
      border-left: 4px solid var(--group-color);
      background: color-mix(in srgb, var(--group-color) 12%, #ffffff);
      font-size: 0.85rem;
    }}

    .priority-count .label {{
      font-weight: 600;
    }}

    .priority-count .value {{
      font-family: "Space Grotesk", sans-serif;
      font-weight: 600;
    }}

    .priority-ticket {{
      display: flex;
      background: var(--card-bg);
      border: 1px solid #e2e8f0;
      border-radius: 8px;
      overflow: hidden;
      margin-bottom: 0.75rem;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
      transition: transform 150ms ease, box-shadow 150ms ease;
    }}

    .priority-ticket:hover {{
      transform: translateY(-1px);
      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
    }}

    .ticket-sidebar {{
      width: 60px;
      display: flex;
      align-items: center;
      justify-content: center;
      color: #ffffff;
      font-weight: 700;
      text-align: center;
      line-height: 1.1;
      order: 0;
    }}

    .ticket-date {{
      display: flex;
      flex-direction: column;
      align-items: center;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}

    .ticket-date .day {{
      font-size: 1.05rem;
    }}

    .ticket-date .month {{
      font-size: 0.7rem;
    }}

    .ticket-content {{
      flex: 1;
      padding: 1rem;
      order: 1;
    }}

    .ticket-header {{
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 0.5rem;
    }}

    .ticket-type {{
      font-size: 0.75rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--text-muted);
    }}

    .ticket-title {{
      font-weight: 600;
      font-size: 1.05rem;
      margin: 0.25rem 0;
    }}

    .ticket-missing {{
      color: #e53e3e;
      font-size: 0.9rem;
    }}

    .filter-row {{
      display: grid;
      gap: 1rem;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    }}

    .filter-status {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.75rem 1.5rem;
    }}

    .filter-status label {{
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
    }}

    .to-top {{
      position: fixed;
      right: 1.5rem;
      bottom: 1.5rem;
      z-index: 50;
      opacity: 0;
      transform: translateY(8px);
      pointer-events: none;
      transition: opacity 200ms ease, transform 200ms ease;
    }}

    .to-top.is-visible {{
      opacity: 1;
      transform: translateY(0);
      pointer-events: auto;
    }}

    .is-hidden {{
      display: none !important;
    }}

    .group-details {{
      width: 100%;
    }}
    
    .collapse > summary {{
       list-style: none;
    }}
    .collapse > summary::-webkit-details-marker {{
       display: none;
    }}

    /* Split layout means we don't need padding-right hack for absolute arrow */
    .collapse-title {{
      position: relative;
      max-width: 100%;
      padding-right: 1.5rem;
    }}
    
    /* Rotate the SVG chevron when open */
    .collapse[open] .chevron {{
      transform: rotate(180deg);
    }}

    .card, .group-card, .collapse-title, .collapse-content {{
      max-width: 100%;
    }}

    .table {{
      width: 100%;
      table-layout: fixed;
    }}

    .table th, .table td {{
      word-break: break-word;
    }}

    @media (max-width: 640px) {{
      .group-link {{
        grid-template-columns: 1fr;
      }}
      .group-badges {{
        justify-items: start;
      }}
      .interest-groups-card {{
        max-height: none;
        overflow: visible;
        position: static;
      }}
      .priority-ticket {{
        flex-direction: column;
      }}
      .ticket-sidebar {{
        width: 100%;
        padding: 0.5rem 0;
      }}
    }}

    .reveal {{
      animation: rise 480ms ease both;
    }}

    @keyframes rise {{
      from {{
        opacity: 0;
        transform: translateY(8px);
      }}
      to {{
        opacity: 1;
        transform: translateY(0);
      }}
    }}

    @keyframes quickFade {{
      from {{
        opacity: 0;
        transform: translateY(-6px);
      }}
      to {{
        opacity: 1;
        transform: translateY(0);
      }}
    }}

    @media (prefers-reduced-motion: reduce) {{
      .reveal {{
        animation: none;
      }}
    }}

    /* Custom Calendar Grid Styles */
    .custom-calendar-card {{
      background: #fff;
      max-width: 100%;
    }}

    .cal-grid {{
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 4px;
      text-align: center;
    }}

    .cal-header {{
      font-size: 0.75rem;
      font-weight: 700;
      color: var(--text-muted);
      padding-bottom: 8px;
    }}

    .cal-cell {{
      aspect-ratio: 1 / 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: flex-start;
      padding-top: 4px;
      border-radius: 6px;
      border: 1px solid transparent;
      background: transparent;
      cursor: pointer;
      position: relative;
      transition: background 0.15s;
    }}

    .cal-cell.empty {{
      cursor: default;
    }}

    .cal-cell:hover:not(.empty) {{
      background-color: #f3f4f6;
    }}

    .cal-cell.is-selected {{
      background-color: #ebf8ff;
      border-color: #4299e1;
      color: #2b6cb0;
    }}

    .cal-cell.is-focused {{
      outline: 2px solid #1d4ed8;
      outline-offset: 1px;
    }}

    .cal-cell.is-today .day-num {{
      background-color: var(--text-main);
      color: #fff;
      border-radius: 50%;
      width: 24px;
      height: 24px;
      line-height: 24px;
      display: block;
    }}

    .day-num {{
      font-size: 0.9rem;
      font-weight: 600;
      line-height: 1.2;
      z-index: 2;
    }}

    .cal-count {{
      margin-top: 2px;
      font-size: 0.65rem;
      line-height: 1.1;
      display: grid;
      gap: 1px;
      z-index: 2;
    }}

    .cal-count .count-total {{
      font-weight: 700;
      color: var(--text-main);
    }}

    .cal-count .count-issues {{
      font-weight: 600;
      color: #b45309;
    }}

    .cal-dots-row {{
      display: flex;
      gap: 2px;
      margin-top: 2px;
      height: 6px;
      justify-content: center;
    }}

    .cal-cell.heat-0 {{
      background: transparent;
    }}

    .cal-cell.heat-1 {{
      background: rgba(254, 243, 199, 0.7);
    }}

    .cal-cell.heat-2 {{
      background: rgba(253, 230, 138, 0.7);
    }}

    .cal-cell.heat-3 {{
      background: rgba(252, 211, 77, 0.7);
    }}

    .cal-cell.heat-4 {{
      background: rgba(251, 191, 36, 0.75);
    }}

    .cal-cell.issues-hidden {{
      visibility: hidden;
    }}

    .calendar-tooltip {{
      position: absolute;
      left: 50%;
      bottom: calc(100% + 6px);
      transform: translateX(-50%) translateY(4px);
      background: rgba(15, 23, 42, 0.95);
      color: #fff;
      padding: 6px 8px;
      border-radius: 6px;
      font-size: 0.65rem;
      line-height: 1.2;
      white-space: nowrap;
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.15s, transform 0.15s;
      z-index: 10;
    }}

    .cal-cell:hover .calendar-tooltip {{
      opacity: 1;
      transform: translateX(-50%) translateY(0);
    }}

    .cal-grid-dot {{
      width: 5px;
      height: 5px;
      border-radius: 50%;
      background: var(--group-color);
    }}

    .calendar-wrapper {{
      display: grid;
      gap: 0.75rem;
    }}

    .calendar-sticky {{
      position: sticky;
      top: 1rem;
      align-self: start;
    }}

    .calendar-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.5rem;
    }}

    .calendar-controls {{
      display: grid;
      gap: 0.4rem;
    }}

    .calendar-controls-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.4rem;
    }}

    .calendar-toggle {{
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      font-size: 0.75rem;
      color: var(--text-muted);
    }}

    .calendar-events {{
      display: grid;
      gap: 0.5rem;
    }}

    .calendar-events-header {{
      font-family: "Space Grotesk", sans-serif;
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: var(--text-muted);
    }}

    .calendar-empty {{
      display: none;
      font-size: 0.75rem;
      opacity: 0.6;
    }}

    .calendar-empty.is-visible {{
      display: block;
    }}

    .cal-events-list {{
      flex-grow: 1;
      display: flex;
      flex-wrap: wrap;
      gap: 0.35rem;
    }}

    .calendar-agenda {{
      display: grid;
      gap: 0.35rem;
    }}

    .calendar-agenda-summary {{
      font-size: 0.75rem;
      color: var(--text-muted);
    }}

    .calendar-agenda-list {{
      display: grid;
      gap: 0.45rem;
    }}

    .agenda-item {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 0.5rem;
      padding: 0.5rem 0.6rem;
      border-radius: 0.6rem;
      border: 1px solid #e2e8f0;
      background: #fff;
    }}

    .agenda-title {{
      font-size: 0.8rem;
      font-weight: 600;
    }}

    .agenda-meta {{
      font-size: 0.7rem;
      color: var(--text-muted);
    }}

    .agenda-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.25rem;
    }}

    @media (max-width: 768px) {{
      #calendar-collapse-toggle {{
        display: inline-flex;
      }}

      #calendar-card.is-collapsed .calendar-wrapper {{
        display: none;
      }}

      #calendar-card.is-collapsed .calendar-events {{
        display: none;
      }}
    }}

    @media (min-width: 769px) {{
      #calendar-collapse-toggle {{
        display: none;
      }}
    }}

    .cal-pill {{
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      padding: 0.2rem 0.5rem;
      border-radius: 999px;
      font-size: 0.7rem;
      font-weight: 600;
      text-decoration: none;
      color: var(--text-main);
      background: color-mix(in srgb, var(--group-color) 15%, white);
      border-width: 1.5px;
      border-color: var(--group-color);
      transition: transform 0.1s;
    }}

    .cal-pill:hover {{
      transform: scale(1.05);
    }}

    .cal-pill.border-dashed {{
      border-style: dashed;
    }}

    .cal-pill.border-solid {{
      border-style: solid;
    }}

    .cal-dot {{
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--group-color);
    }}

    {group_color_css_text}
  </style>
</head>
<body>
  <nav class="navbar bg-base-100 shadow-sm sticky top-0 z-50 px-4 py-2 mb-6" style="background-color: rgba(255,255,255,0.95); backdrop-filter: blur(4px);">
    <div class="flex-1">
      <span class="text-xl font-bold tracking-tight" style="color: var(--col-blue)">CrickNet Checker</span>
    </div>
    <div class="flex-none items-center gap-2">
      <!-- Actionable Toggle -->
      <label class="cursor-pointer label p-0 mr-4 hidden md:flex">
        <span class="label-text mr-2 text-xs font-semibold uppercase opacity-60">Actionable only</span> 
        <input type="checkbox" class="toggle toggle-sm toggle-error" id="actionable-toggle" />
      </label>
      
      <!-- Mobile Actionable Toggle (Compact) -->
       <label class="cursor-pointer label p-0 mr-2 md:hidden">
        <input type="checkbox" class="toggle toggle-xs toggle-error" id="actionable-toggle-mobile" />
      </label>

      <div class="divider divider-horizontal mx-1"></div>
      
      <!-- Links -->
      <a href="#priority" class="btn btn-ghost btn-sm hidden sm:inline-flex">Priority</a>
      <a href="#group-nav" class="btn btn-ghost btn-sm hidden sm:inline-flex">Groups</a>
      
      <!-- Actions -->
      <button class="btn btn-ghost btn-sm btn-square" onclick="window.print()" title="Save as PDF">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z" /></svg>
      </button>
      <button class="btn btn-ghost btn-sm btn-square" onclick="toggleAllGroups(true)" title="Expand All">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 13l-7 7-7-7m14-8l-7 7-7-7" /></svg>
      </button>
      <button class="btn btn-ghost btn-sm btn-square" onclick="toggleAllGroups(false)" title="Collapse All">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7" /></svg>
      </button>
    </div>
  </nav>

  <div class="max-w-7xl mx-auto px-2.5 py-4 md:py-8">
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">
      <div class="stat-box bg-white p-4 rounded-lg shadow-sm border border-slate-100">
        <div class="text-xs uppercase font-bold text-slate-400">Report Generated</div>
        <div class="text-lg font-medium">{generated_friendly}</div>
      </div>
      <div class="stat-box bg-white p-4 rounded-lg shadow-sm border border-slate-100">
        <div class="text-xs uppercase font-bold text-slate-400">Spreadsheet Data</div>
        <div class="text-lg font-medium">Refreshed {source_updated_friendly}</div>
        <div class="text-xs text-slate-500 mt-1">{next_update_html}</div>
      </div>
    </div>

    <div class="grid gap-6 lg:grid-cols-[460px_minmax(0,1fr)]">
      <aside id="group-nav" class="space-y-4 min-w-0">
        <div class="card bg-base-100 shadow quick-summary">
          <div class="card-body p-4">
            <div class="text-xs uppercase tracking-wide opacity-70">Quick summary</div>
            <div class="mt-2 text-sm">
              <div class="font-semibold">{total_confirmed} confirmed</div>
              <div>{total_ok} OK</div>
              <div class="text-error">{total_missing} missing on listings</div>
              <div class="text-warning">{total_check} check</div>
            </div>
            <div class="mt-3 text-xs opacity-70">{summary_line}</div>
          </div>
        </div>

        <div id="calendar-card" class="card bg-base-100 shadow calendar-sticky" data-report-date="{report_date_iso}">
          <div class="card-body p-4">
            <div class="calendar-header">
              <div class="text-xs uppercase tracking-wide opacity-70">Calendar</div>
              <button class="btn btn-ghost btn-xs" id="calendar-collapse-toggle" type="button" aria-expanded="true">Collapse</button>
            </div>

            <div class="calendar-controls mt-2">
              <div class="calendar-controls-row">
                <button class="btn btn-xs btn-outline" id="calendar-jump-today" type="button">Jump to today</button>
                <button class="btn btn-xs btn-outline" id="calendar-jump-issue" type="button">Jump to next issue</button>
                <button class="btn btn-xs btn-ghost" id="calendar-view-toggle" type="button">Month</button>
              </div>
              <div class="calendar-controls-row">
                <label class="calendar-toggle">
                  <input type="checkbox" class="checkbox checkbox-xs" id="calendar-issues-only" />
                  <span>Issues only</span>
                </label>
                <label class="calendar-toggle">
                  <input type="checkbox" class="checkbox checkbox-xs" id="calendar-search-toggle" checked />
                  <span>Search affects calendar</span>
                </label>
              </div>
            </div>

            <div class="calendar-wrapper">
              <div class="custom-calendar-card bg-base-100 border border-base-300 shadow-lg rounded-box p-4">
                <div class="cal-top-bar mb-4 flex justify-between items-center">
                  <span class="text-lg font-bold tracking-tight" id="calendar-month-label">Month</span>
                  <div class="flex gap-1">
                    <select id="calendar-month-select" class="select select-xs select-bordered" aria-label="Jump to month"></select>
                    <button class="btn btn-xs btn-ghost btn-square" id="calendar-prev" type="button" aria-label="Previous month">◀</button>
                    <button class="btn btn-xs btn-ghost btn-square" id="calendar-next" type="button" aria-label="Next month">▶</button>
                  </div>
                </div>
                <div class="cal-grid" id="calendar-grid"></div>
              </div>

              <div class="calendar-events mt-2">
                <div class="calendar-events-header" id="calendar-events-title">Events</div>
                <div class="cal-events-list" id="calendar-events-list">
                  {calendar_pills_html}
                </div>
                <div class="calendar-empty" id="calendar-events-empty">No events on this date.</div>
              </div>
            </div>

            <div class="calendar-agenda mt-4" id="calendar-agenda">
              <div class="calendar-events-header">Agenda</div>
              <div class="calendar-agenda-summary" id="calendar-agenda-summary"></div>
              <div class="calendar-agenda-list" id="calendar-agenda-list"></div>
              <div class="calendar-empty" id="calendar-agenda-empty">No items for this date.</div>
            </div>
          </div>
        </div>

        <div class="card bg-base-100 shadow interest-groups-card">
          <div class="card-body p-4">
            <div class="text-xs uppercase tracking-wide opacity-70">Interest groups</div>
            <div class="mt-3 flex gap-2">
              <button type="button" class="btn btn-xs btn-outline tooltip" data-tip="Show internal only" data-category-preset="internal">Internal</button>
              <button type="button" class="btn btn-xs btn-outline tooltip" data-tip="Show external only" data-category-preset="external">External</button>
              <button type="button" class="btn btn-xs btn-ghost tooltip" data-tip="Show both" data-category-preset="all">All</button>
            </div>
            <ul class="mt-3 space-y-2">
              {group_nav_html}
            </ul>
          </div>
        </div>
      </aside>

      <main class="space-y-6 min-w-0">
        <section id="summary" class="card bg-base-100 shadow reveal">
          <div class="card-body p-5 md:p-6">
            <div class="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
              <div>
                <h2 class="text-xl font-semibold">At a glance</h2>
                <p class="text-sm opacity-80 mt-1">Overview of confirmed entries and checks against site listings.</p>
              </div>
              <div class="summary-stats">
                <div class="summary-stat">
                  <div class="label">Confirmed</div>
                  <div class="value">{total_confirmed}</div>
                </div>
                <div class="summary-stat value-ok">
                  <div class="label">OK</div>
                  <div class="value">{total_ok}</div>
                </div>
                <div class="summary-stat value-missing">
                  <div class="label">Missing</div>
                  <div class="value">{total_missing}</div>
                </div>
                <div class="summary-stat value-check">
                  <div class="label">Check</div>
                  <div class="value">{total_check}</div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section id="filters" class="card bg-base-100 shadow reveal">
          <div class="card-body p-5 md:p-6">
            <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
              <div>
                <h2 class="text-xl font-semibold">Filters</h2>
                <p class="text-sm opacity-80 mt-1">Filter by group, status, or search for a speaker/lab.</p>
              </div>
              <div class="filter-actions">
                <button id="clear-filters" class="btn btn-ghost btn-sm">Clear filters</button>
              </div>
            </div>
            <div class="mt-4 filter-row">
              <div>
                <label class="text-xs uppercase tracking-wide opacity-70" for="filter-search">Search</label>
                <input id="filter-search" class="input input-bordered w-full mt-2" type="search" placeholder="Search speaker, lab, or note" />
              </div>
              <div>
                <label class="text-xs uppercase tracking-wide opacity-70" for="filter-group">Interest group</label>
                <select id="filter-group" class="select select-bordered w-full mt-2">
                  <option value="all">All groups</option>
                  {group_filter_options}
                </select>
              </div>
              <div>
                 <label class="text-xs uppercase tracking-wide opacity-70" for="filter-category">Category</label>
                 <select id="filter-category" class="select select-bordered w-full mt-2">
                    <option value="all">All Categories</option>
                    <option value="internal">Internal</option>
                    <option value="external">External</option>
                 </select>
              </div>
            </div>
            <div class="mt-4 filter-status">
              <label>
                <input type="checkbox" class="checkbox checkbox-success" name="status-filter" value="ok" checked />
                <span>OK</span>
              </label>
              <label>
                <input type="checkbox" class="checkbox checkbox-error" name="status-filter" value="missing" checked />
                <span>Missing</span>
              </label>
              <label>
                <input type="checkbox" class="checkbox checkbox-warning" name="status-filter" value="check" checked />
                <span>Check</span>
              </label>
              <label>
                <input type="checkbox" class="checkbox checkbox-neutral" name="status-filter" value="extra" checked />
                <span>Extra</span>
              </label>
            </div>
          </div>
        </section>

        <section id="priority" class="card bg-base-100 shadow reveal">
          <div class="card-body p-0">
            <details class="collapse collapse-arrow">
              <summary class="collapse-title px-6 py-5 cursor-pointer">
                <div class="space-y-3">
                  <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-2">
                    <div class="text-xl font-semibold">High priority (next 14 days)</div>
                    <div class="flex flex-wrap gap-2">
                      <span class="badge badge-neutral">{priority_group_count} group(s)</span>
                      <span class="badge badge-ghost">{priority_item_count} item(s)</span>
                    </div>
                  </div>
                  <div class="priority-counts">
                    {priority_summary_items}
                  </div>
                </div>
              </summary>
              <div class="collapse-content px-6 pb-6">
                <div>
                  {priority_cards}
                </div>
              </div>
            </details>
          </div>
        </section>

        <section id="groups" class="space-y-5">
          {group_html}
        </section>
      </main>
    </div>
  </div>

  <button id="to-top" class="btn btn-primary btn-sm to-top" aria-label="Back to top">Top</button>

  <script>
    window.CALENDAR_EVENTS = {calendar_events_json};

    function toggleAllGroups(openState) {{
      document.querySelectorAll("details.group-details").forEach((el) => {{
        el.open = openState;
      }});
    }}

    const summaryCard = document.querySelector(".quick-summary");
    const calendarCard = document.querySelector("#calendar-card");
    const summarySection = document.querySelector("#summary");
    function syncCalendarVisibility() {{
      if (!calendarCard || !summaryCard) return;
      calendarCard.classList.toggle("is-hidden", summaryCard.classList.contains("is-visible"));
    }}
    if (summaryCard && summarySection && "IntersectionObserver" in window) {{
      const observer = new IntersectionObserver(
        (entries) => {{
          entries.forEach((entry) => {{
            if (entry.isIntersecting) {{
              summaryCard.classList.remove("is-visible");
            }} else {{
              summaryCard.classList.add("is-visible");
            }}
            syncCalendarVisibility();
          }});
        }},
        {{ root: null, threshold: 0.2 }}
      );
      observer.observe(summarySection);
    }} else if (summaryCard) {{
      summaryCard.classList.add("is-visible");
      syncCalendarVisibility();
    }}

    const groupCards = Array.from(document.querySelectorAll(".group-card[data-group]"));
    const navLinks = Array.from(document.querySelectorAll("[data-group-link]"));
    const linkByGroup = {{}};
    navLinks.forEach((link) => {{
      linkByGroup[link.getAttribute("data-group-link")] = link;
    }});

    function setActiveGroup(slug) {{
      if (!slug) return;
      navLinks.forEach((l) => l.classList.remove("is-active"));
      const link = linkByGroup[slug];
      if (link) {{
        link.classList.add("is-active");
      }}
    }}

    function updateActiveGroup() {{
      const visible = groupCards.filter((card) => !card.classList.contains("is-hidden"));
      if (!visible.length) return;

      const inView = visible.filter((card) => {{
        const rect = card.getBoundingClientRect();
        return rect.top < window.innerHeight && rect.bottom > 0;
      }});

      if (!inView.length) {{
        navLinks.forEach((l) => l.classList.remove("is-active"));
        return;
      }}

      const targetY = 140;
      let best = null;
      let bestDist = Infinity;
      inView.forEach((card) => {{
        const top = card.getBoundingClientRect().top;
        const dist = Math.abs(top - targetY);
        if (dist < bestDist) {{
          bestDist = dist;
          best = card;
        }}
      }});

      if (best) {{
        setActiveGroup(best.getAttribute("data-group"));
      }}
    }}

    navLinks.forEach((link) => {{
      link.addEventListener("click", () => {{
        setActiveGroup(link.getAttribute("data-group-link"));
      }});
    }});

    const filterGroup = document.querySelector("#filter-group");
    const filterCategory = document.querySelector("#filter-category");
    const filterSearch = document.querySelector("#filter-search");
    const statusInputs = Array.from(document.querySelectorAll('input[name="status-filter"]'));
    const clearFilters = document.querySelector("#clear-filters");
    const actionableToggle = document.querySelector("#actionable-toggle");
    const actionableToggleMobile = document.querySelector("#actionable-toggle-mobile");

    function statusChecked(value) {{
      const input = statusInputs.find((el) => el.value === value);
      return input ? input.checked : false;
    }}

    function selectedRowStatuses() {{
      const selected = new Set();
      statusInputs.forEach((input) => {{
        if (!input.checked) return;
        if (input.value === "missing") {{
          selected.add("bad");
        }} else if (input.value === "check") {{
          selected.add("warn");
          selected.add("date_mismatch");
        }} else {{
          selected.add(input.value);
        }}
      }});
      if (selected.size === 0) {{
        ["ok", "warn", "bad", "extra", "date_mismatch"].forEach((st) => selected.add(st));
      }}
      return selected;
    }}
    
    function getActionableState() {{
        if (actionableToggle && actionableToggle.offsetParent !== null) return actionableToggle.checked;
        if (actionableToggleMobile && actionableToggleMobile.offsetParent !== null) return actionableToggleMobile.checked;
        return (actionableToggle ? actionableToggle.checked : false);
    }}
    
    function syncActionableToggles() {{
        const val = this.checked;
        if (actionableToggle) actionableToggle.checked = val;
        if (actionableToggleMobile) actionableToggleMobile.checked = val;
        applyFilters();
    }}

    function applyFilters() {{
      const groupValue = filterGroup ? filterGroup.value : "all";
      const categoryValue = filterCategory ? filterCategory.value : "all";
      const searchValue = filterSearch ? filterSearch.value.trim().toLowerCase() : "";
      const selectedStatuses = selectedRowStatuses();
      const showMissing = statusChecked("missing");
      const showCheck = statusChecked("check");
      const showExtra = statusChecked("extra");
      
      const onlyActionable = getActionableState();

      groupCards.forEach((card) => {{
        const groupSlug = card.getAttribute("data-group");
        const hasIssues = card.getAttribute("data-has-issues") === "true";
        
        let groupMatch = (groupValue === "all" || groupValue === groupSlug);
        
        if (onlyActionable && !hasIssues) {{
           groupMatch = false;
        }}

        const dateCards = Array.from(card.querySelectorAll(".date-card"));

        if (!dateCards.length) {{
           const visible = groupMatch;
           card.classList.toggle("is-hidden", !visible);
           const link = linkByGroup[groupSlug];
           if (link) {{
             const li = link.closest("li");
             if (li) li.classList.toggle("is-hidden", !visible);
           }}
           return;
        }}

        let cardVisible = false;
        dateCards.forEach((dateCard) => {{
          const cardCat = dateCard.getAttribute("data-category") || "";
          let categoryMatch = true;
          if (categoryValue !== "all") {{
            if (categoryValue === "external") {{
              categoryMatch = cardCat.includes("external");
            }} else {{
              categoryMatch = cardCat.includes(categoryValue);
            }}
          }}

          const cardMatch = groupMatch && categoryMatch;
          dateCard.setAttribute("data-card-match", cardMatch ? "1" : "0");
          if (!cardMatch) {{
            dateCard.classList.add("is-hidden");
            return;
          }}

          let rowVisible = false;
          const rows = Array.from(dateCard.querySelectorAll("tbody tr"));
          rows.forEach((row) => {{
            const status = row.getAttribute("data-status") || "";
            
            const actionableMatch = !(onlyActionable && status === "ok");
            const statusMatch = selectedStatuses.has(status);
            const textMatch = !searchValue || row.textContent.toLowerCase().includes(searchValue);
            const baseMatch = actionableMatch && statusMatch;
            row.setAttribute("data-match-base", baseMatch ? "1" : "0");
            row.setAttribute("data-match-search", textMatch ? "1" : "0");
            const show = baseMatch && textMatch;
            row.classList.toggle("is-hidden", !show);
            if (show) rowVisible = true;
          }});

          const details = Array.from(dateCard.querySelectorAll("[data-detail]"));
          details.forEach((block) => {{
            const detailType = block.getAttribute("data-detail");
            let allow = true;
            if (detailType === "missing") {{
              allow = showMissing;
            }} else if (detailType === "extra") {{
              allow = showExtra;
            }} else if (detailType === "likely") {{
              allow = showCheck || showExtra;
            }} else if (detailType === "date-mismatch") {{
              allow = showCheck;
            }}
            block.classList.toggle("is-hidden", !allow || !rowVisible);
          }});

          dateCard.classList.toggle("is-hidden", !rowVisible);
          if (rowVisible) cardVisible = true;
        }});
        
        card.classList.toggle("is-hidden", !groupMatch || !cardVisible);
        const link = linkByGroup[groupSlug];
        if (link) {{
          const li = link.closest("li");
          if (li) li.classList.toggle("is-hidden", !groupMatch || !cardVisible);
        }}
      }});

      updateActiveGroup();
      rebuildCalendarModel();
      updateUrlState();
    }}

    if (filterGroup) filterGroup.addEventListener("change", applyFilters);
    if (filterCategory) filterCategory.addEventListener("change", applyFilters);
    if (filterSearch) filterSearch.addEventListener("input", applyFilters);
    if (actionableToggle) actionableToggle.addEventListener("change", syncActionableToggles);
    if (actionableToggleMobile) actionableToggleMobile.addEventListener("change", syncActionableToggles);
    statusInputs.forEach((input) => input.addEventListener("change", applyFilters));
    
    if (clearFilters) {{
      clearFilters.addEventListener("click", () => {{
        if (filterGroup) filterGroup.value = "all";
        if (filterCategory) filterCategory.value = "all";
        if (filterSearch) filterSearch.value = "";
        if (actionableToggle) actionableToggle.checked = false;
        if (actionableToggleMobile) actionableToggleMobile.checked = false;
        statusInputs.forEach((input) => {{
          input.checked = true;
        }});
        applyFilters();
      }});
    }}

    const toTopButton = document.querySelector("#to-top");
    function updateToTop() {{
      if (!toTopButton) return;
      if (window.scrollY > 400) {{
        toTopButton.classList.add("is-visible");
      }} else {{
        toTopButton.classList.remove("is-visible");
      }}
    }}
    if (toTopButton) {{
      toTopButton.addEventListener("click", () => {{
        window.scrollTo({{ top: 0, behavior: "smooth" }});
      }});
    }}

    let scrollTicking = false;
    function onScroll() {{
      if (scrollTicking) return;
      scrollTicking = true;
      requestAnimationFrame(() => {{
        updateActiveGroup();
        updateToTop();
        scrollTicking = false;
      }});
    }}

    window.addEventListener("scroll", onScroll, {{ passive: true }});
    window.addEventListener("resize", () => {{
      updateActiveGroup();
    }});

    function setCountdownValue(el, value) {{
      if (!el) return;
      const v = Math.max(0, value | 0);
      el.style.setProperty("--value", v);
      el.setAttribute("aria-label", String(v));
      el.textContent = String(v);
    }}

    function startNextUpdateCountdown() {{
      const wrap = document.querySelector("#next-update-countdown");
      if (!wrap) return;

      const targetEpoch = parseInt(wrap.getAttribute("data-target-epoch") || "", 10);
      if (!Number.isFinite(targetEpoch)) return;

      const hEl = document.querySelector("#cd-hours");
      const mEl = document.querySelector("#cd-mins");
      const sEl = document.querySelector("#cd-secs");
      if (!hEl || !mEl || !sEl) return;

      function tick() {{
        const now = Math.floor(Date.now() / 1000);
        let remaining = targetEpoch - now;

        if (remaining <= 0) {{
          wrap.innerHTML = "<span>Spreadsheet update is due (scheduled &gt; 6 hrs ago).</span>";
          return;
        }}

        const hours = Math.floor(remaining / 3600);
        remaining %= 3600;
        const mins = Math.floor(remaining / 60);
        const secs = remaining % 60;

        setCountdownValue(hEl, hours);
        setCountdownValue(mEl, mins);
        setCountdownValue(sEl, secs);
      }}

      tick();
      setInterval(tick, 1000);
    }}

    // Sidebar quick filters (Internal / External / All)
    document.querySelectorAll("[data-category-preset]").forEach((btn) => {{
      btn.addEventListener("click", () => {{
        const v = btn.getAttribute("data-category-preset") || "all";
        const sel = document.querySelector("#filter-category");
        if (!sel) return;
        sel.value = v;
        sel.dispatchEvent(new Event("change"));
      }});
    }});

    const calendarGrid = document.querySelector("#calendar-grid");
    const calendarMonthLabel = document.querySelector("#calendar-month-label");
    const calendarPrev = document.querySelector("#calendar-prev");
    const calendarNext = document.querySelector("#calendar-next");
    const calendarEvents = Array.from(document.querySelectorAll("[data-cal-date]"));
    const calendarEmpty = document.querySelector("#calendar-events-empty");
    const calendarTitle = document.querySelector("#calendar-events-title");
    const calendarAgendaList = document.querySelector("#calendar-agenda-list");
    const calendarAgendaSummary = document.querySelector("#calendar-agenda-summary");
    const calendarAgendaEmpty = document.querySelector("#calendar-agenda-empty");
    const calendarJumpToday = document.querySelector("#calendar-jump-today");
    const calendarJumpIssue = document.querySelector("#calendar-jump-issue");
    const calendarViewToggle = document.querySelector("#calendar-view-toggle");
    const calendarIssuesOnly = document.querySelector("#calendar-issues-only");
    const calendarSearchToggle = document.querySelector("#calendar-search-toggle");
    const calendarCollapseToggle = document.querySelector("#calendar-collapse-toggle");
    const calendarMonthSelect = document.querySelector("#calendar-month-select");
    const calendarEventsData = window.CALENDAR_EVENTS || calendarEvents.map((el) => {{
      const dateIso = el.getAttribute("data-cal-date") || "";
      const groupClass = Array.from(el.classList).find((cls) => cls.startsWith("group-")) || "";
      const groupSlug = groupClass.replace("group-", "");
      const groupLabel = el.getAttribute("title") || groupSlug || "Group";
      const anchor = (el.getAttribute("href") || "").replace(/^#/, "");
      const shortLabelEl = el.querySelector(".cal-text");
      const shortLabel = shortLabelEl ? shortLabelEl.textContent.trim() : "";
      const isExternal = el.classList.contains("border-dashed");
      return {{
        date_iso: dateIso,
        group_slug: groupSlug,
        group_label: groupLabel,
        category: isExternal ? "External" : "Internal",
        anchor,
        short_label: shortLabel,
      }};
    }});

    function formatCalendarHeader(iso) {{
      if (!iso) return "Events";
      const parsed = new Date(iso + "T00:00:00");
      if (Number.isNaN(parsed.getTime())) return "Events";
      return "Events on " + parsed.toLocaleDateString("en-GB", {{
        weekday: "short",
        day: "2-digit",
        month: "short",
      }});
    }}

    function buildIsoDate(year, monthIndex, day) {{
      const m = String(monthIndex + 1).padStart(2, "0");
      const d = String(day).padStart(2, "0");
      return `${{year}}-${{m}}-${{d}}`;
    }}

    const todayObj = new Date();
    const todayStr = buildIsoDate(todayObj.getFullYear(), todayObj.getMonth(), todayObj.getDate());

    let focusDate = todayStr;
    let selectedDates = new Set([todayStr]);
    let currentMonth = new Date(todayObj.getFullYear(), todayObj.getMonth(), 1);
    let calendarView = "month";

    let calendarModel = {{
      byDate: new Map(),
      issueDates: [],
      eventDates: [],
    }};

    function blankDateInfo() {{
      return {{
        total: 0,
        ok: 0,
        missing: 0,
        check: 0,
        extra: 0,
        dateMismatch: 0,
        issues: 0,
        groups: new Map(),
        agenda: [],
      }};
    }}

    function addGroupIssue(info, groupLabel) {{
      if (!groupLabel) return;
      const prev = info.groups.get(groupLabel) || 0;
      info.groups.set(groupLabel, prev + 1);
    }}

    function buildCalendarModel() {{
      const model = {{
        byDate: new Map(),
        issueDates: [],
        eventDates: [],
      }};
      const dateCards = Array.from(document.querySelectorAll(".date-card"));
      dateCards.forEach((card) => {{
        const cardMatch = card.getAttribute("data-card-match");
        const includeSearch = calendarSearchToggle ? calendarSearchToggle.checked : true;
        if (cardMatch === "0") return;
        if (includeSearch && card.classList.contains("is-hidden")) return;
        const dateIso = card.getAttribute("data-date") || "";
        if (!dateIso) return;
        const groupLabel = card.getAttribute("data-group-label") || card.getAttribute("data-group") || "Group";
        const groupUrl = card.getAttribute("data-group-url") || "";
        const category = card.getAttribute("data-category") || "";
        const anchor = card.getAttribute("id") || "";
        const titleEl = card.querySelector(".text-sm.font-medium");
        const cardTitle = titleEl ? titleEl.textContent.trim() : "Agenda item";
        const rows = Array.from(card.querySelectorAll("tbody tr"));

        rows.forEach((row) => {{
          const baseMatch = row.getAttribute("data-match-base");
          const searchMatch = row.getAttribute("data-match-search");
          const matchesBase = baseMatch !== "0";
          const matchesSearch = searchMatch !== "0";
          const includeSearch = calendarSearchToggle ? calendarSearchToggle.checked : true;
          if (!matchesBase) return;
          if (includeSearch && !matchesSearch) return;
          const status = row.getAttribute("data-status") || "";
          const cells = row.querySelectorAll("td");
          const expected = cells[1] ? cells[1].textContent.trim() : "";
          const found = cells[2] ? cells[2].textContent.trim() : "";
          const note = cells[3] ? cells[3].textContent.trim() : "";
          const title = expected || found || cardTitle;

          let info = model.byDate.get(dateIso);
          if (!info) {{
            info = blankDateInfo();
            model.byDate.set(dateIso, info);
          }}

          info.total += 1;
          if (status === "ok") {{
            info.ok += 1;
          }} else if (status === "bad") {{
            info.missing += 1;
            addGroupIssue(info, groupLabel);
          }} else if (status === "warn") {{
            info.check += 1;
            addGroupIssue(info, groupLabel);
          }} else if (status === "date_mismatch") {{
            info.check += 1;
            info.dateMismatch += 1;
            addGroupIssue(info, groupLabel);
          }} else if (status === "extra") {{
            info.extra += 1;
          }}

          info.agenda.push({{
            date: dateIso,
            status,
            title,
            groupLabel,
            groupUrl,
            category,
            anchor,
            note,
          }});
        }});
      }});

      model.byDate.forEach((info, dateIso) => {{
        info.issues = info.missing + info.check;
        if (info.total > 0) model.eventDates.push(dateIso);
        if (info.issues > 0) model.issueDates.push(dateIso);
      }});

      model.eventDates.sort();
      model.issueDates.sort();
      return model;
    }}

    function getHeatClass(issues) {{
      if (issues <= 0) return "heat-0";
      if (issues === 1) return "heat-1";
      if (issues <= 3) return "heat-2";
      if (issues <= 6) return "heat-3";
      return "heat-4";
    }}

    function formatTooltip(info) {{
      if (!info) return "";
      const topGroups = Array.from(info.groups.entries())
        .sort((a, b) => b[1] - a[1])
        .slice(0, 2)
        .map(([name, count]) => `${{name}} (${{count}})`);
      const summary = `OK ${{info.ok}} / Missing ${{info.missing}} / Check ${{info.check}} / Extra ${{info.extra}}`;
      if (!topGroups.length) return summary;
      return `${{summary}} · Top: ${{topGroups.join(", ")}}`;
    }}

    function rebuildCalendarModel() {{
      calendarModel = buildCalendarModel();
      populateMonthSelect();
      const hasVisibleSelection = Array.from(selectedDates).some((d) => calendarModel.byDate.has(d));
      if (!hasVisibleSelection) {{
        applyDefaultSelection();
        return;
      }}
      updateCalendarEvents(focusDate);
      renderCalendar();
      renderAgenda();
      updateUrlState();
    }}

    function renderCalendar() {{
      if (!calendarGrid) return;
      calendarGrid.innerHTML = "";

      const weekdayHeaders = ["M", "T", "W", "T", "F"];
      weekdayHeaders.forEach((label) => {{
        const cell = document.createElement("div");
        cell.className = "cal-header";
        cell.textContent = label;
        calendarGrid.appendChild(cell);
      }});

      const monthYearLabel = currentMonth.toLocaleDateString("en-GB", {{
        month: "long",
        year: "numeric",
      }});
      if (calendarMonthLabel) {{
        if (calendarView === "week") {{
          const focusObj = new Date((focusDate || todayStr) + "T00:00:00");
          const weekLabel = Number.isNaN(focusObj.getTime())
            ? monthYearLabel
            : focusObj.toLocaleDateString("en-GB", {{ day: "2-digit", month: "short", year: "numeric" }});
          calendarMonthLabel.textContent = `Week of ${{weekLabel}}`;
        }} else {{
          calendarMonthLabel.textContent = monthYearLabel;
        }}
      }}

      if (calendarMonthSelect) {{
        calendarMonthSelect.disabled = calendarView !== "month";
      }}

      const year = currentMonth.getFullYear();
      const month = currentMonth.getMonth();
      const renderDates = [];
      let leadingEmpty = 0;
      let trailingEmpty = 0;

      if (calendarView === "week") {{
        let base = new Date((focusDate || todayStr) + "T00:00:00");
        if (Number.isNaN(base.getTime())) base = new Date();
        const start = new Date(base);
        const offset = (start.getDay() + 6) % 7;
        start.setDate(start.getDate() - offset);
        for (let i = 0; i < 7; i += 1) {{
          renderDates.push(new Date(start.getFullYear(), start.getMonth(), start.getDate() + i));
        }}
      }} else {{
        const firstDay = new Date(year, month, 1);
        leadingEmpty = (firstDay.getDay() + 6) % 7; // Monday-first
        const daysInMonth = new Date(year, month + 1, 0).getDate();
        for (let day = 1; day <= daysInMonth; day += 1) {{
          renderDates.push(new Date(year, month, day));
        }}
        const totalCells = leadingEmpty + daysInMonth;
        trailingEmpty = (7 - (totalCells % 7)) % 7;
      }}

      for (let i = 0; i < leadingEmpty; i += 1) {{
        const empty = document.createElement("div");
        empty.className = "cal-cell empty";
        calendarGrid.appendChild(empty);
      }}

      renderDates.forEach((dateObj) => {{
        const dateIso = buildIsoDate(dateObj.getFullYear(), dateObj.getMonth(), dateObj.getDate());
        const cell = document.createElement("button");
        cell.type = "button";
        cell.className = "cal-cell day";
        if (dateIso === todayStr) cell.classList.add("is-today");
        if (selectedDates.has(dateIso)) cell.classList.add("is-selected");
        if (dateIso === focusDate) cell.classList.add("is-focused");
        cell.setAttribute("data-date", dateIso);

        const dayNum = document.createElement("span");
        dayNum.className = "day-num";
        dayNum.textContent = String(dateObj.getDate());
        cell.appendChild(dayNum);

        const info = calendarModel.byDate.get(dateIso);
        if (info && info.total > 0) {{
          cell.classList.add(getHeatClass(info.issues));
          const count = document.createElement("div");
          count.className = "cal-count";
          const issueLabel = `${{info.missing}}M ${{info.check}}C`;
          count.innerHTML = `<span class="count-total">${{info.total}}</span><span class="count-issues">${{issueLabel}}</span>`;
          cell.appendChild(count);

          const dotsRow = document.createElement("div");
          dotsRow.className = "cal-dots-row";
          cell.appendChild(dotsRow);

          const tooltip = document.createElement("div");
          tooltip.className = "calendar-tooltip";
          tooltip.textContent = formatTooltip(info);
          cell.appendChild(tooltip);
        }} else {{
          cell.classList.add("heat-0");
        }}

        if (calendarIssuesOnly && calendarIssuesOnly.checked && (!info || info.issues === 0)) {{
          cell.classList.add("issues-hidden");
        }}

        cell.addEventListener("click", (event) => {{
          handleDateClick(event, dateIso);
        }});
        calendarGrid.appendChild(cell);
      }});

      for (let i = 0; i < trailingEmpty; i += 1) {{
        const empty = document.createElement("div");
        empty.className = "cal-cell empty";
        calendarGrid.appendChild(empty);
      }}
    }}

    function parseIsoToDate(iso) {{
      if (!iso) return null;
      const parsed = new Date(iso + "T00:00:00");
      if (Number.isNaN(parsed.getTime())) return null;
      return parsed;
    }}

    function buildDateRange(startIso, endIso) {{
      const start = parseIsoToDate(startIso);
      const end = parseIsoToDate(endIso);
      if (!start || !end) return [];
      const dates = [];
      const step = start <= end ? 1 : -1;
      const cursor = new Date(start);
      while ((step > 0 && cursor <= end) || (step < 0 && cursor >= end)) {{
        dates.push(buildIsoDate(cursor.getFullYear(), cursor.getMonth(), cursor.getDate()));
        cursor.setDate(cursor.getDate() + step);
      }}
      return dates;
    }}

    function updateCalendarEvents(dateIso) {{
      let visibleCount = 0;
      calendarEvents.forEach((eventEl) => {{
        const eventDate = eventEl.getAttribute("data-cal-date") || "";
        const show = (eventDate === dateIso);
        eventEl.classList.toggle("is-hidden", !show);
        if (show) visibleCount += 1;
      }});

      if (calendarTitle) calendarTitle.textContent = formatCalendarHeader(dateIso);
      if (calendarEmpty) {{
        if (visibleCount === 0) {{
          calendarEmpty.textContent = "No events on this date.";
          calendarEmpty.classList.add("is-visible");
        }} else {{
          calendarEmpty.classList.remove("is-visible");
        }}
      }}
    }}

    function renderAgenda() {{
      if (!calendarAgendaList) return;
      calendarAgendaList.innerHTML = "";

      const sortedDates = Array.from(selectedDates).sort();
      let total = 0;
      let missing = 0;
      let check = 0;
      let extra = 0;
      let ok = 0;
      const items = [];

      sortedDates.forEach((dateIso) => {{
        const info = calendarModel.byDate.get(dateIso);
        if (!info) return;
        total += info.total;
        missing += info.missing;
        check += info.check;
        extra += info.extra;
        ok += info.ok;
        info.agenda.forEach((item) => items.push(item));
      }});

      if (calendarAgendaSummary) {{
        if (total > 0) {{
          calendarAgendaSummary.textContent = `${{total}} items · Missing ${{missing}} · Check ${{check}} · Extra ${{extra}} · OK ${{ok}}`;
        }} else {{
          calendarAgendaSummary.textContent = "";
        }}
      }}

      if (calendarAgendaEmpty) {{
        calendarAgendaEmpty.classList.toggle("is-visible", items.length === 0);
      }}

      items.sort((a, b) => a.date.localeCompare(b.date));
      items.forEach((item) => {{
        const statusLabel = item.status === "bad"
          ? "Missing"
          : (item.status === "warn" || item.status === "date_mismatch")
            ? "Check"
            : (item.status === "extra" ? "Extra" : "OK");

        const entry = document.createElement("div");
        entry.className = "agenda-item";

        const main = document.createElement("div");
        const titleEl = document.createElement("div");
        titleEl.className = "agenda-title";
        titleEl.textContent = item.title || "Agenda item";
        const metaEl = document.createElement("div");
        metaEl.className = "agenda-meta";
        metaEl.textContent = `${{item.groupLabel || "Group"}} · ${{statusLabel}} · ${{item.date}}`;
        main.appendChild(titleEl);
        main.appendChild(metaEl);

        const actions = document.createElement("div");
        actions.className = "agenda-actions";

        const copyBtn = document.createElement("button");
        copyBtn.type = "button";
        copyBtn.className = "btn btn-xs btn-ghost";
        copyBtn.textContent = "Copy";
        copyBtn.addEventListener("click", () => {{
          const text = ` ${{item.title}} (${{item.groupLabel || "Group"}}) - ${{statusLabel}}`;
          if (navigator.clipboard && navigator.clipboard.writeText) {{
            navigator.clipboard.writeText(text);
          }}
        }});

        const openLink = document.createElement("a");
        openLink.className = "btn btn-xs btn-ghost";
        openLink.textContent = "Open";
        openLink.href = item.anchor ? `#${{item.anchor}}` : "#";

        actions.appendChild(copyBtn);
        actions.appendChild(openLink);

        if (item.groupUrl) {{
          const sourceLink = document.createElement("a");
          sourceLink.className = "btn btn-xs btn-ghost";
          sourceLink.textContent = "Source";
          sourceLink.href = item.groupUrl;
          sourceLink.target = "_blank";
          actions.appendChild(sourceLink);
        }}

        entry.appendChild(main);
        entry.appendChild(actions);
        calendarAgendaList.appendChild(entry);
      }});
    }}

    function setSelection(datesLike, newFocus) {{
      const nextDates = Array.isArray(datesLike) ? datesLike : Array.from(datesLike || []);
      selectedDates = new Set(nextDates);
      if (newFocus) {{
        focusDate = newFocus;
      }} else if (nextDates.length) {{
        focusDate = nextDates[nextDates.length - 1];
      }}

      const focusObj = parseIsoToDate(focusDate);
      if (focusObj) {{
        currentMonth = new Date(focusObj.getFullYear(), focusObj.getMonth(), 1);
      }}

      updateCalendarEvents(focusDate);
      renderCalendar();
      renderAgenda();
    }}

    function handleDateClick(event, dateIso) {{
      if (!dateIso) return;
      if (event.shiftKey && focusDate) {{
        const range = buildDateRange(focusDate, dateIso);
        setSelection(range, dateIso);
      }} else if (event.ctrlKey || event.metaKey) {{
        const next = new Set(selectedDates);
        if (next.has(dateIso)) {{
          next.delete(dateIso);
        }} else {{
          next.add(dateIso);
        }}
        setSelection(next, dateIso);
      }} else {{
        setSelection([dateIso], dateIso);
      }}
      scrollToDate(dateIso);
    }}

    function scrollToDate(dateIso) {{
      if (!dateIso) return;
      const target = document.querySelector(`.date-card[data-date="${{dateIso}}"]:not(.is-hidden)`);
      if (target) {{
        target.scrollIntoView({{ behavior: "smooth", block: "start" }});
      }}
    }}

    function jumpToNextIssue() {{
      const list = calendarModel.issueDates;
      if (!list.length) return;
      const base = focusDate || todayStr;
      let next = list.find((d) => d >= base);
      if (!next) next = list[0];
      setSelection([next], next);
      scrollToDate(next);
    }}

    function jumpToToday() {{
      setSelection([todayStr], todayStr);
      scrollToDate(todayStr);
    }}

    function populateMonthSelect() {{
      if (!calendarMonthSelect) return;
      const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
      const year = currentMonth.getFullYear();
      calendarMonthSelect.innerHTML = "";
      monthNames.forEach((label, idx) => {{
        const option = document.createElement("option");
        option.value = String(idx);
        option.textContent = `${{label}} ${{year}}`;
        if (idx === currentMonth.getMonth()) {{
          option.selected = true;
        }}
        calendarMonthSelect.appendChild(option);
      }});
    }}

    function applyDefaultSelection() {{
      const calendarCardEl = document.querySelector("#calendar-card");
      const reportIso = calendarCardEl ? (calendarCardEl.getAttribute("data-report-date") || "") : "";
      const baseIso = reportIso || todayStr;
      if (calendarModel.eventDates.length) {{
        const upcoming = calendarModel.eventDates.find((d) => d >= baseIso);
        const fallback = upcoming || calendarModel.eventDates[calendarModel.eventDates.length - 1];
        setSelection([fallback], fallback);
        return;
      }}
      setSelection([baseIso], baseIso);
    }}

    function setFocusDate(dateIso) {{
      if (!dateIso) return;
      focusDate = dateIso;
      const focusObj = parseIsoToDate(focusDate);
      if (focusObj) {{
        currentMonth = new Date(focusObj.getFullYear(), focusObj.getMonth(), 1);
      }}
      renderCalendar();
    }}

    function moveFocusBy(days) {{
      const base = parseIsoToDate(focusDate || todayStr) || new Date();
      base.setDate(base.getDate() + days);
      const next = buildIsoDate(base.getFullYear(), base.getMonth(), base.getDate());
      setFocusDate(next);
    }}

    function updateViewToggleLabel() {{
      if (!calendarViewToggle) return;
      calendarViewToggle.textContent = calendarView === "month" ? "Month" : "Week";
    }}

    // URL params: date=YYYY-MM-DD&group=...&status=...&category=...&q=...
    function updateUrlState() {{
      const params = new URLSearchParams();
      if (focusDate) params.set("date", focusDate);
      if (selectedDates.size > 1) {{
        params.set("dates", Array.from(selectedDates).sort().join(","));
      }}
      if (filterGroup && filterGroup.value && filterGroup.value !== "all") {{
        params.set("group", filterGroup.value);
      }}
      if (filterCategory && filterCategory.value && filterCategory.value !== "all") {{
        params.set("category", filterCategory.value);
      }}
      if (filterSearch && filterSearch.value.trim()) {{
        params.set("q", filterSearch.value.trim());
      }}
      if (statusInputs.length) {{
        const statuses = statusInputs.filter((input) => input.checked).map((input) => input.value);
        if (statuses.length && statuses.length !== statusInputs.length) {{
          params.set("status", statuses.join(","));
        }}
      }}
      if (getActionableState()) params.set("actionable", "1");
      if (calendarView !== "month") params.set("view", calendarView);
      if (calendarIssuesOnly && calendarIssuesOnly.checked) params.set("issuesOnly", "1");
      if (calendarSearchToggle && calendarSearchToggle.checked) params.set("searchCal", "1");

      const qs = params.toString();
      const nextUrl = qs ? `${{window.location.pathname}}?${{qs}}` : window.location.pathname;
      history.replaceState(null, "", nextUrl);
    }}

    function applyUrlState() {{
      const params = new URLSearchParams(window.location.search);
      const group = params.get("group");
      const category = params.get("category");
      const q = params.get("q");
      const status = params.get("status");
      const date = params.get("date");
      const dates = params.get("dates");
      const view = params.get("view");
      const actionable = params.get("actionable");
      const issuesOnly = params.get("issuesOnly");
      const searchCal = params.get("searchCal");

      if (filterGroup && group) filterGroup.value = group;
      if (filterCategory && category) filterCategory.value = category;
      if (filterSearch && q !== null) filterSearch.value = q;

      if (status) {{
        const allowed = new Set(status.split(",").map((s) => s.trim()).filter(Boolean));
        statusInputs.forEach((input) => {{
          input.checked = allowed.has(input.value);
        }});
      }}

      if (actionable === "1") {{
        if (actionableToggle) actionableToggle.checked = true;
        if (actionableToggleMobile) actionableToggleMobile.checked = true;
      }}

      if (view === "week" || view === "month") {{
        calendarView = view;
        updateViewToggleLabel();
      }}

      if (calendarIssuesOnly && issuesOnly === "1") {{
        calendarIssuesOnly.checked = true;
      }}

      if (calendarSearchToggle && searchCal === "1") {{
        calendarSearchToggle.checked = true;
      }}

      let nextDates = [];
      if (dates) {{
        nextDates = dates.split(",").map((d) => d.trim()).filter(Boolean);
      }} else if (date) {{
        nextDates = [date];
      }}
      if (nextDates.length) {{
        selectedDates = new Set(nextDates);
        focusDate = nextDates[nextDates.length - 1];
        const focusObj = parseIsoToDate(focusDate);
        if (focusObj) {{
          currentMonth = new Date(focusObj.getFullYear(), focusObj.getMonth(), 1);
        }}
      }}
    }}

    window.filterDate = function(isoDate) {{
      if (!isoDate) return;
      setSelection([isoDate], isoDate);
    }};

    if (calendarPrev) {{
      calendarPrev.addEventListener("click", () => {{
        currentMonth = new Date(currentMonth.getFullYear(), currentMonth.getMonth() - 1, 1);
        populateMonthSelect();
        renderCalendar();
      }});
    }}
    if (calendarNext) {{
      calendarNext.addEventListener("click", () => {{
        currentMonth = new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 1);
        populateMonthSelect();
        renderCalendar();
      }});
    }}

    if (calendarMonthSelect) {{
      calendarMonthSelect.addEventListener("change", () => {{
        const nextMonth = parseInt(calendarMonthSelect.value, 10);
        if (Number.isFinite(nextMonth)) {{
          currentMonth = new Date(currentMonth.getFullYear(), nextMonth, 1);
          renderCalendar();
        }}
      }});
    }}

    if (calendarViewToggle) {{
      calendarViewToggle.addEventListener("click", () => {{
        calendarView = calendarView === "month" ? "week" : "month";
        updateViewToggleLabel();
        renderCalendar();
        updateUrlState();
      }});
      updateViewToggleLabel();
    }}

    if (calendarIssuesOnly) {{
      calendarIssuesOnly.addEventListener("change", () => {{
        renderCalendar();
        updateUrlState();
      }});
    }}

    if (calendarSearchToggle) {{
      calendarSearchToggle.addEventListener("change", () => {{
        rebuildCalendarModel();
        updateUrlState();
      }});
    }}

    if (calendarJumpToday) {{
      calendarJumpToday.addEventListener("click", () => {{
        jumpToToday();
      }});
    }}

    if (calendarJumpIssue) {{
      calendarJumpIssue.addEventListener("click", () => {{
        jumpToNextIssue();
      }});
    }}

    if (calendarCollapseToggle && calendarCard) {{
      const setCollapseState = (collapsed) => {{
        calendarCard.classList.toggle("is-collapsed", collapsed);
        calendarCollapseToggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
        calendarCollapseToggle.textContent = collapsed ? "Expand" : "Collapse";
      }};

      const initialCollapsed = window.matchMedia("(max-width: 768px)").matches;
      setCollapseState(initialCollapsed);
      calendarCollapseToggle.addEventListener("click", () => {{
        setCollapseState(!calendarCard.classList.contains("is-collapsed"));
      }});
    }}

    document.addEventListener("keydown", (event) => {{
      const tag = (event.target && event.target.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select") return;

      if (event.key === "ArrowLeft") {{
        event.preventDefault();
        moveFocusBy(-1);
      }} else if (event.key === "ArrowRight") {{
        event.preventDefault();
        moveFocusBy(1);
      }} else if (event.key === "ArrowUp") {{
        event.preventDefault();
        moveFocusBy(-7);
      }} else if (event.key === "ArrowDown") {{
        event.preventDefault();
        moveFocusBy(7);
      }} else if (event.key === "Enter") {{
        if (focusDate) setSelection([focusDate], focusDate);
      }} else if (event.key === "n") {{
        currentMonth = new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 1);
        populateMonthSelect();
        renderCalendar();
      }} else if (event.key === "p") {{
        currentMonth = new Date(currentMonth.getFullYear(), currentMonth.getMonth() - 1, 1);
        populateMonthSelect();
        renderCalendar();
      }} else if (event.key === "t") {{
        jumpToToday();
      }}
    }});

    applyUrlState();
    calendarModel = buildCalendarModel();
    populateMonthSelect();
    applyDefaultSelection();

    applyFilters();
    startNextUpdateCountdown();
    updateToTop();
  </script>
</body>
</html>
"""
    return html

def write_report_files(report_html: str) -> Tuple[str, str]:
    base = Path(__file__).resolve().parent
    reports_dir = base / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(LOCAL_TZ).strftime("%Y%m%d_%H%M%S")
    stamped_path = reports_dir / f"report_{ts}.html"
    latest_path = reports_dir / "latest.html"

    stamped_path.write_text(report_html, encoding="utf-8")
    latest_path.write_text(report_html, encoding="utf-8")
    return str(latest_path), str(stamped_path)

def fetch_fresh_data_via_trigger(context, page, interactive: bool) -> bool:
    """
    1. Uploads a dummy file to trigger Power Automate.
    2. Waits for the JSON file to update (by checking the 'lastUpdated' field).
    3. Downloads the fresh JSON.
    """
    print("Starting Data Refresh Sequence...")
    
    # 1. Ensure we are logged in so we can get the security token
    if not ensure_sharepoint_logged_in(page, interactive=interactive):
        return False

    # 2. Get the Request Digest via SharePoint contextinfo (no DOM scraping)
    digest = get_sharepoint_request_digest(context)
    if not digest:
        print("❌ Failed to get security token. Cannot trigger flow.")
        return False

    # 3. Get the OLD timestamp (so we know when it changes)
    old_timestamp = ""
    if Path(LOCAL_JSON_PATH).exists():
        try:
            old_data = json.loads(Path(LOCAL_JSON_PATH).read_text(encoding="utf-8"))
            old_timestamp = old_data.get("lastUpdated", "")
            print(f"   Current Data Timestamp: {old_timestamp}")
        except:
            pass

    # 4. Upload 'trigger.txt' (Overwriting the old one)
    # We put the current time in the file so the checksum always changes
    trigger_content = f"Triggered by Python at {datetime.now().isoformat()}"
    
    # SharePoint REST API endpoint for file creation
    # Note the 'overwrite=true' flag - this replaces the old file automatically
    upload_url = (
        f"{SHAREPOINT_SITE}/sites/ScienceOperationsAdministration/_api/web"
        f"/GetFolderByServerRelativeUrl('{TRIGGER_FOLDER_REL_PATH}')"
        f"/Files/add(url='{TRIGGER_FILENAME}',overwrite=true)"
    )

    print(f"   Uploading trigger file to: {TRIGGER_FILENAME}...")
    resp = context.request.post(
        upload_url,
        headers={
            "accept": "application/json;odata=verbose",
            "content-type": "text/plain",
            "X-RequestDigest": digest
        },
        data=trigger_content
    )

    if not resp.ok:
        print(f"❌ Trigger upload failed: {resp.status} {resp.status_text}")
        return False
    
    print("✅ Trigger uploaded! Waiting for Power Automate (this takes ~1-2 mins)...")

    # 5. POLLING LOOP: Wait for the JSON to update
    # We check every 10 seconds for up to 3 minutes (18 attempts)
    max_retries = 18 
    for i in range(max_retries):
        time.sleep(10) # Wait 10 seconds
        
        print(f"   Checking for updates (Attempt {i+1}/{max_retries})...")
        
        # Try to download the JSON
        dl_resp = context.request.get(
            SHAREPOINT_DOWNLOAD_URL,
            headers={"accept": "application/json"},
        )
        
        if dl_resp.ok:
            new_content = dl_resp.body()
            try:
                new_json = json.loads(new_content)
                new_timestamp = new_json.get("lastUpdated", "")
                
                # Compare timestamps
                if new_timestamp != old_timestamp:
                    print(f"✅ Fresh data detected! (Timestamp: {new_timestamp})")
                    Path(LOCAL_JSON_PATH).write_bytes(new_content)
                    return True
            except:
                pass # JSON might be partial or invalid while writing, just retry
        
    print("⚠️  Timed out waiting for data refresh. Using existing data.")
    return False



    return str(latest_path), str(stamped_path)


# ---------------------------
# Main run
# ---------------------------
def run_once(headless: bool, interactive: bool) -> Tuple[bool, bool]:
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=headless,
            channel=CHROME_CHANNEL,
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        cricknet_ok = ensure_logged_in(page, interactive=interactive)
        if not cricknet_ok:
            try:
                page.close()
            except Exception:
                pass
            context.close()
            return False, False

        sharepoint_ok = False
        try:
            # We now use the smart trigger function
            sharepoint_ok = fetch_fresh_data_via_trigger(context, page, interactive=interactive)
        except Exception as e:
            print(f"❌ Error in refresh process: {e}")
            sharepoint_ok = False

        close_extra_tabs(context, page)

        print("✅ Logged into CrickNet (Profile button detected).")
        if sharepoint_ok:
            print(f"✅ Downloaded SharePoint data to: {LOCAL_JSON_PATH}")
            try:
                raw = json.loads(Path(LOCAL_JSON_PATH).read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    lu = str(raw.get("lastUpdated", "")).strip()
                    recs = raw.get("records", [])
                    if lu:
                        print(f"   Source lastUpdated: {lu}")
                    if isinstance(recs, list):
                        print(f"   Records: {len(recs)}")
            except Exception:
                pass
        else:
            print("⚠️  Could not download SharePoint JSON (will use local copy if present).")

        external_found_by_group: Dict[str, Dict[str, List[Dict[str, str]]]] = {}
        external_scrape_ok = False
        global_external_lookup: Dict[str, List[Dict[str, Any]]] = {}
        try:
            print("Scraping external seminars from crick.ac.uk...")
            external_seminars = scrape_external_seminars()
            external_found_by_group = build_external_found_by_group(external_seminars)
            global_external_lookup = build_external_website_lookup(external_seminars)
            external_scrape_ok = True
            print(f"✅ External website seminars scraped: {len(external_seminars)}")
        except Exception:
            print("⚠️  External website scrape failed (skipping external website check).")

        # Build report model scaffold
        report = build_report_model()

        # Fill group comparisons
        priority_items: List[Dict[str, Any]] = []

        for g in report["groups"]:
            display_name = str(g["display"])
            json_name = str(g["json"])
            events_url = str(g["url"])

            # Expected
            if Path(LOCAL_JSON_PATH).exists():
                expected_map = load_expected_from_json(LOCAL_JSON_PATH, json_name)
            else:
                expected_map = {}

            # Found
            events = scrape_interest_group_events(page, events_url)
            found_map = build_found_map(events)
            
            # Build speaker lookups for cross-date matching
            cricknet_speaker_lookup = build_global_speaker_lookup(found_map)
            spreadsheet_speaker_lookup = build_global_speaker_lookup(expected_map)

            # We want to iterate by all (date, category) keys
            all_keys = sorted(set(expected_map.keys()) | set(found_map.keys()))
            sections: List[Dict[str, Any]] = []

            # For each date/category build comparison rows
            for (d, cat) in all_keys:
                exp_items = expected_map.get((d, cat), [])
                got_items = found_map.get((d, cat), [])

                if not exp_items and not got_items:
                    continue

                rows, summary = build_comparison_rows(
                    exp_items, got_items, 
                    source_label="CrickNet",
                    current_date=d,
                    cricknet_speaker_lookup=cricknet_speaker_lookup,
                    spreadsheet_speaker_lookup=spreadsheet_speaker_lookup,
                    external_website_lookup=(global_external_lookup if cat == "External" else None)
                )

                # Title shown in report: we keep it simple
                title = "Interest group seminar"

                missing = summary.get("missing_exact", [])
                date_mismatches = summary.get("date_mismatches", [])
                extras = summary.get("extras_exact", [])
                likely_pairs = summary.get("likely_pairs", [])
                any_mismatch = bool(summary.get("any_mismatch", False))

                has_missing = bool(missing)
                has_date_mismatch = bool(date_mismatches)

                section = {
                    "date_iso": d,
                    "date_uk": iso_to_uk(d),
                    "category": cat,
                    "title": title,
                    "rows": rows,
                    "any_mismatch": any_mismatch,
                    "has_missing": has_missing,
                    "has_date_mismatch": has_date_mismatch,
                    "missing": missing,
                    "date_mismatches": date_mismatches,
                    "extras": extras,
                    "likely_pairs": likely_pairs,
                    "source_label": "CrickNet",
                }
                sections.append(section)

                # Priority: next 14 days AND missing expected speakers on CrickNet
                if within_next_days(d, PRIORITY_WINDOW_DAYS) and cat in {"Internal", "External"} and missing:
                    priority_items.append({
                        "group": display_name,
                        "date_iso": d,
                        "date_uk": iso_to_uk(d),
                        "category": cat,
                        "title": title,
                        "missing": missing,
                        "url": events_url,
                    })

            if external_scrape_ok:
                external_expected: Dict[str, List[Dict[str, str]]] = {}
                for (d, cat), items in expected_map.items():
                    if cat == "External":
                        external_expected[d] = items

                external_found = external_found_by_group.get(json_name, {})
                
                # Build speaker lookups for external website cross-date matching
                # Convert simple date -> items dict to (date, category) -> items format
                external_expected_map: Dict[Tuple[str, str], List[Dict[str, str]]] = {
                    (d, "External"): items for d, items in external_expected.items()
                }
                external_found_map: Dict[Tuple[str, str], List[Dict[str, str]]] = {
                    (d, "External"): items for d, items in external_found.items()
                }
                external_spreadsheet_lookup = build_global_speaker_lookup(external_expected_map)
                external_website_lookup = build_global_speaker_lookup(external_found_map)
                
                external_dates = sorted(set(external_expected.keys()) | set(external_found.keys()))
                for d in external_dates:
                    exp_items = external_expected.get(d, [])
                    got_items = external_found.get(d, [])
                    if not exp_items and not got_items:
                        continue

                    rows, summary = build_comparison_rows(
                        exp_items, got_items, 
                        source_label="crick.ac.uk",
                        current_date=d,
                        cricknet_speaker_lookup=external_website_lookup,  # Use website lookup for "missing" check
                        spreadsheet_speaker_lookup=external_spreadsheet_lookup  # Use spreadsheet lookup for "extras" check
                    )
                    missing = summary.get("missing_exact", [])
                    date_mismatches = summary.get("date_mismatches", [])
                    extras = summary.get("extras_exact", [])
                    likely_pairs = summary.get("likely_pairs", [])
                    any_mismatch = bool(summary.get("any_mismatch", False))
                    has_missing = bool(missing)

                    sections.append({
                        "date_iso": d,
                        "date_uk": iso_to_uk(d),
                        "category": "External website",
                        "title": "External website seminar",
                        "rows": rows,
                        "any_mismatch": any_mismatch,
                        "has_missing": has_missing,
                        "has_date_mismatch": bool(date_mismatches),
                        "missing": missing,
                        "date_mismatches": date_mismatches,
                        "extras": extras,
                        "likely_pairs": likely_pairs,
                        "source_label": "crick.ac.uk",
                    })

            category_order = {"Internal": 0, "External": 1, "External website": 2}
            sections.sort(key=lambda s: (s.get("date_iso", ""), category_order.get(s.get("category", ""), 99)))
            g["sections"] = sections

        priority_items.sort(key=lambda x: x.get("date_iso", "9999-99-99"))
        report["priority"] = priority_items

        html = render_report_html(report)
        latest_path, stamped_path = write_report_files(html)

        print("")
        print(f"Report written:")
        print(f"   - {latest_path}")
        print(f"   - {stamped_path}")

        try:
            page.close()
        except Exception:
            pass
        context.close()

        return True, sharepoint_ok


def main() -> None:
    crick_ok, sp_ok = run_once(headless=True, interactive=False)

    if not crick_ok or not sp_ok:
        print("\n============================================================")
        print("Login required (CrickNet and/or SharePoint). Opening browser...")
        print("============================================================\n")
        run_once(headless=False, interactive=True)


def login_only() -> None:
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,
            channel=CHROME_CHANNEL,
            viewport={"width": 1280, "height": 900},
        )

        page = context.new_page()
        print("Opening CrickNet login…")
        ensure_logged_in(page, interactive=True)

        print("Opening SharePoint login…")
        ensure_sharepoint_logged_in(page, interactive=True)

        print("\nLogin setup complete.")
        input("You can close the browser now. Press Enter to exit…")
        context.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--login-only", action="store_true")
    args = parser.parse_args()

    if args.login_only:
        login_only()
    else:
        main()
