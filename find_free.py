#!/usr/bin/env python3
"""Find tracks from a Spotify "Liked Songs" CSV export that artists/labels
offer as legal free downloads on Bandcamp ("name your price" / free).

Usage: python3 find_free.py Liked_Songs.csv out_dir

Writes:
  out_dir/free_tracks.csv  - all tracks with Bandcamp match + free status
  out_dir/free_only.csv    - only tracks confirmed free on Bandcamp
For every track it also adds search links (Bandcamp, SoundCloud
"free download", Hypeddit) for manual checking.
"""
import csv, json, re, sys, time, unicodedata, urllib.parse, urllib.request
from difflib import SequenceMatcher
from pathlib import Path

SEARCH = "https://bandcamp.com/api/bcsearch_public_api/1/autocomplete_elastic"
DETAILS = "https://bandcamp.com/api/mobile/24/tralbum_details?band_id={b}&tralbum_id={t}&tralbum_type={k}"
DELAY = 0.6


def http(url, data=None, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data,
                                         headers={"Content-Type": "application/json"} if data else {})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except Exception as e:  # noqa
            err = e
            time.sleep(2 * (i + 1))
    print("  ! request failed:", url[:90], err, file=sys.stderr)
    return None


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(mixed|original mix|radio edit|extended mix|feat\.?|ft\.?)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def base_title(name):
    # "Warm Places - Klartraum Remix - mixed" -> "Warm Places Klartraum Remix"
    name = re.sub(r"\s*-\s*mixed\s*$", "", name, flags=re.I)
    name = re.sub(r"\((feat|ft)\.?[^)]*\)", "", name, flags=re.I)
    return name.replace(" - ", " ").strip()


def match(row_title, artists, res):
    t1, t2 = norm(row_title), norm(res.get("name", ""))
    tsim = SequenceMatcher(None, t1, t2).ratio()
    if t1 and (t1 in t2 or t2 in t1):
        tsim = max(tsim, 0.9)
    hay = " " + norm(res.get("band_name", "") + " " + res.get("name", "")) + " "
    art_ok = any(norm(a) and f" {norm(a)} " in hay for a in artists)
    return tsim if art_ok else 0.0


def is_free(d):
    if not d:
        return False
    if d.get("free_download"):
        return True
    return bool(d.get("is_purchasable")) and (d.get("price") in (0, 0.0)) and not d.get("is_set_price")


def check(row):
    title = base_title(row["Track Name"])
    artists = [a.strip() for a in row["Artist Name(s)"].split(";") if a.strip()]
    q = f"{artists[0] if artists else ''} {title}"
    payload = json.dumps({"search_text": q, "search_filter": "t", "full_page": False, "fan_id": None}).encode()
    res = (http(SEARCH, payload) or {}).get("auto", {}).get("results", [])
    time.sleep(DELAY)
    best, score = None, 0.0
    for r in res:
        s = match(title, artists, r)
        if s > score:
            best, score = r, s
    out = {"bc_match": "", "bc_url": "", "bc_price": "", "bc_free": "no"}
    if not best or score < 0.6:
        return out
    out["bc_match"] = f'{best.get("band_name")} - {best.get("name")}'
    out["bc_url"] = best.get("item_url_path", "")
    d = http(DETAILS.format(b=best["band_id"], t=best["id"], k="t"))
    time.sleep(DELAY)
    if d:
        out["bc_price"] = f'{d.get("price")} {d.get("currency")}' if d.get("is_purchasable") else "not sold separately"
        if is_free(d):
            out["bc_free"] = "YES (track)"
        elif not d.get("is_purchasable") and best.get("album_id"):
            a = http(DETAILS.format(b=best["band_id"], t=best["album_id"], k="a"))
            time.sleep(DELAY)
            if a:
                out["bc_price"] = f'album {a.get("price")} {a.get("currency")}'
                if is_free(a):
                    out["bc_free"] = "YES (album)"
    return out


def links(row):
    q = f'{row["Artist Name(s)"].split(";")[0]} {base_title(row["Track Name"])}'
    e = urllib.parse.quote_plus
    return {
        "search_bandcamp": f"https://bandcamp.com/search?q={e(q)}",
        "search_soundcloud_free": f"https://soundcloud.com/search/sounds?q={e(q + ' free download')}",
        "search_hypeddit": f"https://hypeddit.com/search?q={e(q)}",
    }


def main(src, out_dir):
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(open(src, encoding="utf-8")))
    keep = ["Track Name", "Artist Name(s)", "Album Name", "Record Label", "ISRC", "Release Date"]
    cols = keep + ["bc_free", "bc_price", "bc_match", "bc_url",
                   "search_bandcamp", "search_soundcloud_free", "search_hypeddit"]
    allf = open(out_dir / "free_tracks.csv", "w", newline="", encoding="utf-8")
    w = csv.DictWriter(allf, fieldnames=cols); w.writeheader()
    free = []
    for i, row in enumerate(rows, 1):
        rec = {k: row.get(k, "") for k in keep}
        rec.update(check(row)); rec.update(links(row))
        w.writerow(rec); allf.flush()
        if rec["bc_free"].startswith("YES"):
            free.append(rec)
        print(f"[{i}/{len(rows)}] {rec['bc_free']:12} {row['Artist Name(s)']} - {row['Track Name']}", flush=True)
    allf.close()
    with open(out_dir / "free_only.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(free)
    print(f"Done: {len(free)} free of {len(rows)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
