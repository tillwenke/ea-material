#!/usr/bin/env python3
"""Make an IBIS screen ad (1920 x 1080 PNG) from a Luma event link.

    scripts/ibis.py https://luma.com/abcd1234 [--org ea|zais|bio]
                    [--title ...] [--blurb ...] [--where ...] [-o out.png]

Reads title, time, place and description from the event page, picks the
brand from the event's Luma calendar (override with --org), renders
screens/ibis.tex with LuaLaTeX and writes ibis/<date>-<slug>.png.
Needs lualatex, latexmk, qrencode and pdftoppm.
"""
import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import unicodedata
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build" / "ibis"
TZ = ZoneInfo("Europe/Zurich")

# Luma calendar slug -> brand in screens/style/.
CALENDARS = {"eazurich": "ea", "zais": "zais", "zurich-biosecurity-hub": "bio"}
# (max title length, font size in px); the last entry is the fallback.
TITLE_SIZES = [(18, 150), (32, 124), (56, 100), (90, 80), (None, 68)]
BLURB_MAX = 170


def fetch_event(url):
    """Return the event page's initial data (event, calendar, hosts, ...)."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req, timeout=30).read().decode()
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        sys.exit(f"No event data found at {url}; is it a public Luma event page?")
    data = json.loads(m.group(1))["props"]["pageProps"]["initialData"]["data"]
    if "event" not in data:
        sys.exit(f"{url} looks like a calendar, not a single event.")
    return data


def guess_org(data):
    cal = data.get("calendar") or {}
    if cal.get("slug") in CALENDARS:
        return CALENDARS[cal["slug"]]
    names = " ".join([cal.get("name") or ""] + [h.get("name") or "" for h in data.get("hosts", [])])
    if "AI Safety" in names:
        return "zais"
    if "Biosecurity" in names:
        return "bio"
    return "ea"


def plain(text):
    """Drop emoji and other symbols the brand fonts lack; tidy whitespace and dashes."""
    text = "".join(c for c in text if unicodedata.category(c) not in ("So", "Cs", "Mn")
                   and ord(c) < 0x10000 and c != "\ufe0f")
    text = re.sub(r"\s+-\s+", " – ", text)
    return re.sub(r"\s+", " ", text).strip(" –-|·")


def blurb_from(data):
    """First real paragraph of the description, cut to sentences that fit on screen.
    Short lead-ins (quotes, one-liners) are skipped in favour of the first one
    with at least 80 characters."""
    paras = []
    for node in (data.get("description_mirror") or {}).get("content", []):
        if node.get("type") == "paragraph":
            paras.append(plain("".join(t.get("text", "") for t in node.get("content", []))))
    paras = [p for p in paras if p]
    text = next((p for p in paras if len(p) >= 80), paras[0] if paras else "")
    if len(text) <= BLURB_MAX:
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out = ""
    for s in sentences:
        if len(out) + len(s) + 1 > BLURB_MAX:
            break
        out = f"{out} {s}".strip()
    return out or text[:BLURB_MAX].rsplit(" ", 1)[0] + "…"


def when(event):
    start = dt.datetime.fromisoformat(event["start_at"].replace("Z", "+00:00")).astimezone(TZ)
    end = dt.datetime.fromisoformat(event["end_at"].replace("Z", "+00:00")).astimezone(TZ)
    day = f"{start:%A} {start.day} {start:%B}"
    if end.date() != start.date():
        return start, f"{start:%a} {start.day} {start:%b} – {end:%a} {end.day} {end:%b}", f"from {start:%H:%M}"
    return start, day, f"{start:%H:%M}–{end:%H:%M}"


def where(event):
    if event.get("location_type") == "online":
        return "Online"
    geo = event.get("geo_address_info") or {}
    return plain(geo.get("address") or geo.get("city") or "Zurich")


def tex_escape(text):
    repl = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
            "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\^{}"}
    return "".join(repl.get(c, c) for c in text)


def qr_path(url):
    """The URL's QR code as a TikZ path on a unit grid, origin top-left (as in posters/common/qr)."""
    xpm = subprocess.run(["qrencode", "-t", "XPM", "-s", "1", "-m", "0", "-l", "M", "-o", "-", url],
                         check=True, capture_output=True, text=True).stdout
    rows = re.findall(r'^"([^"]*)",?$', xpm, re.M)
    size = int(rows[0].split()[0])
    dark = next(r[0] for r in rows[1:3] if "#000000" in r)
    rects = []
    for y, row in enumerate(rows[3:3 + size]):
        for m in re.finditer(re.escape(dark) + "+", row):
            rects.append(f"({m.start()},{-y}) rectangle ({m.end()},{-y - 1})")
    lines = [" ".join(rects[i:i + 8]) + "%" for i in range(0, len(rects), 8)]
    return f"\\def\\QrModules{{{size}}}\n\\def\\QrPath{{%\n" + "\n".join(lines) + "\n}\n"


def render(name, org, title, size, blurb, day, place, url_short, qr):
    tex = BUILD / f"{name}.tex"
    defs = {"Org": org, "EventTitle": tex_escape(title), "TitleSize": str(size),
            "TitleLead": str(round(size * 0.96)), "Blurb": tex_escape(blurb),
            "Day": tex_escape(day), "Where": tex_escape(place), "UrlShort": url_short}
    tex.write_text("".join(f"\\newcommand\\{k}{{{v}}}\n" for k, v in defs.items())
                   + qr + "\\input{ibis}\n")
    subprocess.run(["latexmk", "-lualatex", "-interaction=nonstopmode", "-halt-on-error",
                    f"-outdir={BUILD}", str(tex)], cwd=ROOT / "screens", check=True,
                   stdout=subprocess.DEVNULL)
    return "IBIS-OVERLAP" not in (BUILD / f"{name}.log").read_text(errors="replace")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", help="Luma event link, e.g. https://luma.com/abcd1234")
    ap.add_argument("--org", choices=["ea", "zais", "bio"], help="brand (default: from the Luma calendar)")
    ap.add_argument("--title", help="override the event title")
    ap.add_argument("--blurb", help="override the short description ('' for none)")
    ap.add_argument("--where", help="override the location line")
    ap.add_argument("-o", "--out", type=Path, help="output PNG (default ibis/<date>-<slug>.png)")
    args = ap.parse_args()

    data = fetch_event(args.url)
    event = data["event"]
    slug = event["url"]
    org = args.org or guess_org(data)
    title = plain(args.title or event["name"])
    blurb = plain(args.blurb) if args.blurb is not None else blurb_from(data)
    start, day, time = when(event)
    place = f"{time} · {args.where or where(event)}"
    out = args.out or ROOT / "ibis" / f"{start:%Y-%m-%d}-{slug}.png"

    BUILD.mkdir(parents=True, exist_ok=True)
    qr = qr_path(f"https://luma.com/{slug}")
    size = next(s for n, s in TITLE_SIZES if n is None or len(title) <= n)
    # Shrink the title, then drop the blurb, until the text clears the date block.
    while not render(slug, org, title, size, blurb, day, place, f"luma.com/{slug}", qr):
        if size > 64:
            size -= 8
        elif blurb:
            print("Blurb does not fit; dropping it (shorten it with --blurb).", file=sys.stderr)
            blurb, size = "", next(s for n, s in TITLE_SIZES if n is None or len(title) <= n)
        else:
            print("Warning: title still overlaps the date; shorten it with --title.", file=sys.stderr)
            break

    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["pdftoppm", "-png", "-r", "72", "-singlefile", str(BUILD / f"{slug}.pdf"),
                    str(out.with_suffix(""))], check=True)
    print(f"{out}  [{org}] {title} | {day}, {place}")


if __name__ == "__main__":
    main()
