#!/usr/bin/env python3
"""
Krok 3: nahraje slidy na GitHub a publikuje carousel na Instagram.

Instagram si obrazky stahuje z verejne URL, takze repo musi byt VEREJNE.
Token je v promenne prostredi, nikdy v kodu.

Priprava (jednou):
    export IG_TOKEN='...'          # dlouhodoby token
    export IG_USER_ID='...'        # 27363053100063561
    export GH_REPO='uzivatel/repo' # verejne GitHub repo

Pouziti:
    python3 publish.py --dry-run       # ukaze, co by udelal
    python3 publish.py --post 0        # publikuje konkretni post
    python3 publish.py                 # publikuje dalsi ve fronte
    python3 publish.py --refresh-token # obnovi token (nutne >24h stary)
    python3 publish.py --limit         # kolik postu zbyva v 24h limitu
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date

import requests

# ---------------------------------------------------------------
API = "https://graph.instagram.com/v23.0"
BRANCH = "main"
SLIDES_DIR = "docs/posts"        # kam v repu patri obrazky
POLL_TRIES = 10                  # kolikrat se ptat na stav containeru
POLL_WAIT = 6                    # sekundy mezi dotazy
# ---------------------------------------------------------------

TOKEN = os.environ.get("IG_TOKEN", "")
USER_ID = os.environ.get("IG_USER_ID", "")
REPO = os.environ.get("GH_REPO", "")


def need(name, value):
    if not value:
        sys.exit(f"CHYBA: chybi promenna prostredi {name}.")
    return value


def api(method, path, **params):
    """Dotaz na Instagram Graph API. Vraci JSON, pri chybe konci."""
    params["access_token"] = TOKEN
    url = f"{API}/{path}"
    resp = requests.request(method, url, params=params, timeout=60)
    try:
        data = resp.json()
    except ValueError:
        sys.exit(f"CHYBA: nesrozumitelna odpoved ({resp.status_code}).")

    if "error" in data:
        err = data["error"]
        print(f"\nCHYBA INSTAGRAM API", file=sys.stderr)
        print(f"  kod:    {err.get('code')} / "
              f"{err.get('error_subcode', '-')}", file=sys.stderr)
        print(f"  zprava: {err.get('message')}", file=sys.stderr)
        if err.get("code") in (190, 452, 102):
            print("\n  => Token je neplatny. Vygeneruj novy v Meta "
                  "dashboardu.\n     Pozor: zmena hesla na Instagramu "
                  "token vzdy zneplatni.", file=sys.stderr)
        sys.exit(1)
    return data


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


def push_slides(post_index, local_dir):
    """Zkopiruje slidy do repa, commitne a pushne. Vraci verejne URL."""
    dest = os.path.join(SLIDES_DIR, f"post_{post_index:05d}")
    os.makedirs(dest, exist_ok=True)

    urls = []
    for i in range(1, 99):
        src = os.path.join(local_dir, f"slide_{i}.jpg")
        if not os.path.exists(src):
            break
        with open(src, "rb") as f:
            blob = f.read()
        target = os.path.join(dest, f"slide_{i}.jpg")
        with open(target, "wb") as f:
            f.write(blob)
        urls.append(f"https://raw.githubusercontent.com/{REPO}/"
                    f"{BRANCH}/{target}")

    if not urls:
        sys.exit(f"CHYBA: v {local_dir} nejsou zadne slide_N.jpg. "
                 f"Spust nejdriv render_post.py")

    git("add", dest)
    commit = git("commit", "-m", f"slides: post {post_index}")
    if commit.returncode != 0 and "nothing to commit" not in commit.stdout:
        print(commit.stdout, commit.stderr)
    push = git("push", "origin", BRANCH)
    if push.returncode != 0:
        sys.exit(f"CHYBA pri git push:\n{push.stderr}")

    return urls


def wait_public(url, tries=10, wait=3):
    """Pocka, dokud raw.githubusercontent URL neodpovi. CDN ma zpozdeni."""
    for n in range(tries):
        try:
            if requests.head(url, timeout=15, allow_redirects=True).ok:
                return True
        except requests.RequestException:
            pass
        time.sleep(wait)
    return False


def publish_carousel(urls, caption):
    """Trikrokova publikace carouselu."""
    print(f"\n1/3 Vytvarim {len(urls)} item containeru...")
    children = []
    for i, url in enumerate(urls, 1):
        res = api("POST", f"{USER_ID}/media",
                  image_url=url, is_carousel_item="true")
        children.append(res["id"])
        print(f"    slide {i}: {res['id']}")

    print("\n2/3 Vytvarim carousel container...")
    carousel = api("POST", f"{USER_ID}/media",
                   media_type="CAROUSEL",
                   children=",".join(children),
                   caption=caption)
    cid = carousel["id"]
    print(f"    container: {cid}")

    print("\n    cekam na zpracovani...")
    for n in range(POLL_TRIES):
        status = api("GET", cid, fields="status_code")
        code = status.get("status_code")
        print(f"    [{n + 1}/{POLL_TRIES}] {code}")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            sys.exit(f"CHYBA: container skoncil ve stavu {code}.")
        time.sleep(POLL_WAIT)
    else:
        sys.exit("CHYBA: container se nestihl zpracovat.")

    print("\n3/3 Publikuji...")
    media = api("POST", f"{USER_ID}/media_publish", creation_id=cid)
    return media["id"]


def show_limit():
    res = api("GET", f"{USER_ID}/content_publishing_limit",
              fields="config,quota_usage")
    row = res["data"][0]
    quota = row.get("config", {}).get("quota_total", 50)
    used = row.get("quota_usage", 0)
    print(f"Limit za 24 h: {used}/{quota} postu "
          f"({quota - used} zbyva)")


def refresh_token():
    """Obnovi dlouhodoby token. Musi byt starsi nez 24 h."""
    resp = requests.get("https://graph.instagram.com/refresh_access_token",
                        params={"grant_type": "ig_refresh_token",
                                "access_token": TOKEN}, timeout=30)
    data = resp.json()
    if "error" in data:
        print(f"CHYBA: {data['error'].get('message')}", file=sys.stderr)
        sys.exit(1)
    days = data["expires_in"] // 86400
    with open("token_refreshed.json", "w") as f:
        json.dump({"refreshed": date.today().isoformat(),
                   "expires_in_days": days}, f, indent=2)
    print(f"Token obnoven, plati {days} dni.")
    print("Novy token je vypsan nize - uloz ho do IG_TOKEN "
          "(nebo GitHub Secrets):\n")
    print(data["access_token"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--post", type=int, help="index postu")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--refresh-token", action="store_true")
    ap.add_argument("--limit", action="store_true")
    args = ap.parse_args()

    if args.refresh_token:
        need("IG_TOKEN", TOKEN)
        return refresh_token()

    need("IG_TOKEN", TOKEN)
    need("IG_USER_ID", USER_ID)

    if args.limit:
        return show_limit()

    need("GH_REPO", REPO)

    with open("pauper_posts.json", encoding="utf-8") as f:
        posts = json.load(f)
    try:
        with open("publish_state.json", encoding="utf-8") as f:
            pstate = json.load(f)
    except FileNotFoundError:
        pstate = {"next_post": 0, "published": []}

    idx = args.post if args.post is not None else pstate["next_post"]
    if idx >= len(posts):
        sys.exit("Fronta je u konce.")

    post = posts[idx]
    local = os.path.join("out", f"post_{idx:05d}")
    cap_file = os.path.join(local, "caption.txt")
    if not os.path.exists(cap_file):
        sys.exit(f"CHYBA: chybi {cap_file}. Spust nejdriv "
                 f"python3 render_post.py --index {idx}")
    with open(cap_file, encoding="utf-8") as f:
        caption = f.read().strip()

    print(f"Post #{idx}  [{post['set']}] {post['set_name']}  "
          f"({len(post['cards'])} karet)")
    for i, c in enumerate(post["cards"], 1):
        print(f"   {i}. {c['name']}")
    print(f"Caption: {len(caption)} znaku")

    if args.dry_run:
        dest = f"{SLIDES_DIR}/post_{idx:05d}"
        print(f"\n--dry-run: nic se nenahralo ani nepublikovalo.")
        print(f"Slidy by sly do {dest}/ a URL by byly:")
        print(f"  https://raw.githubusercontent.com/{REPO}/{BRANCH}/"
              f"{dest}/slide_1.jpg  (a dalsi)")
        return

    urls = push_slides(idx, local)
    print(f"\nNahrano {len(urls)} slidu na GitHub.")

    print("Cekam, nez budou verejne dostupne...")
    if not wait_public(urls[0]):
        sys.exit("CHYBA: slide_1.jpg neni verejne dostupny. "
                 "Zkontroluj, ze je repo VEREJNE.")
    print("    OK, dostupne.")

    media_id = publish_carousel(urls, caption)
    print(f"\nHOTOVO. Media ID: {media_id}")

    if args.post is None:
        pstate["next_post"] = idx + 1
    pstate.setdefault("published", []).append({
        "post": idx, "media_id": media_id,
        "when": date.today().isoformat(), "set": post["set"],
    })
    with open("publish_state.json", "w", encoding="utf-8") as f:
        json.dump(pstate, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
