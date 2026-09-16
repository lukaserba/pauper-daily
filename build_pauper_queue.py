#!/usr/bin/env python3
"""
Krok 1: vygeneruje chronologicky serazenou frontu Pauper-legal karet
a rovnou ji rozseka na carousely.

Radi se podle data vydani printu, nikdy nemicha dva sety v jednom postu.

Pouziti:
    python3 -m pip install --user requests
    python3 build_pauper_queue.py

Vystup:
    pauper_queue.json   plocha fronta vsech karet
    pauper_posts.json   tataz fronta rozsekana po CAROUSEL_SIZE
                        (tenhle soubor cte render_post.py)

Nastaveni je nize v sekci MODE / CAROUSEL_SIZE / POSTS_PER_DAY.
"""

import json
import os
import sys
import time
import requests

API = "https://api.scryfall.com/cards/search"

CACHE_FILE = "scryfall_raw.json"    # syrova data ze Scryfall
CACHE_MAX_DAYS = 7                  # jak dlouho je cache platna
REQUEST_DELAY = 0.25                # pauza mezi dotazy (Scryfall chce >=0.1)

# game:paper  -> zadne Arena/MTGO-only printy
# r:c         -> pouze common printy (to je to, co dela kartu Pauper-legal)
# legal:pauper-> pojistka, ze karta neni banned
QUERY = "legal:pauper r:c game:paper"

HEADERS = {
    "User-Agent": "PauperDailyBot/1.0 (kontakt@example.com)",
    "Accept": "application/json",
}

# ---------------------------------------------------------------
# ZMEN TOTO SLOVO podle toho, co chces:
#   "cards"  = kazda karta jednou (nejstarsi common print)   ~10 000
#   "art"    = kazdy unikatni artwork jednou                 ~15 000
#   "prints" = uplne vsechny printy vcetne reprintu          ~40 000
MODE = "prints"

CAROUSEL_SIZE = 5   # karet v jednom postu
POSTS_PER_DAY = 2   # jen pro vypocet, kolik let to potrva

# Cele kategorie setu, ktere do fronty nechceme.
# POZOR: "funny" tu schvalne NENI - Unfinity commons jsou Pauper-legal.
# Acorn karty odfiltruje uz samotne legal:pauper.
SKIP_SET_TYPES = {
    "memorabilia",      # Collector's Edition, International Edition, WC decky
    "token",            # tokeny, nejsou to karty
    "minigame",         # miniher z boosteru
    "alchemy",          # digitalni
    "treasure_chest",   # MTGO odmeny
    "promo",            # promo sety, dotiskuji se porad dokola
}

# Konkretni sety navic (kody malymi pismeny).
SKIP_SETS = {
    "plst",             # The List - prubezne se meni
    "sld", "slx",       # Secret Lair - nepravidelne dotisky
    "mb1", "mb2", "cmb1", "cmb2", "fmb1",   # Mystery Booster
    "30a",              # 30th Anniversary Edition, nelegalni
    "ptg",              # Ponies: The Galloping
    "dbl",              # Innistrad: Double Feature - MID+VOW bez nove karty
    "phuk",             # Hachette UK - magazinove promo inserty
    # cizojazycne dotisky - tytez karty, jen jinym jazykem
    "fbb",              # Foreign Black Border
    "4bb",              # Fourth Edition Foreign Black Border
    "bchr",             # Chronicles Foreign Black Border
    "ren", "rin",       # Renaissance / Rinascimento
    "sal", "psal",      # Salvat 2005
    "ps11",             # Salvat 2011
}

# Vyradi i jednotlive promo printy uvnitr normalnich setu
# (prerelease razitka, buy-a-box, promo packy...)
SKIP_PROMO_PRINTS = True

# Basic landy nemaji mana cost ani text - v captionu by zely prazdnotou.
SKIP_BASIC_LANDS = True

# Vyradi printy podle promo_types.
SKIP_PROMO_TYPES = {
    "mediainsert",      # magazinove inserty, stejna kategorie jako PHUK
    "schinesealtart",   # zjednodusena cinstina s alternativnim artworkem
    "boosterfun",       # showcase / borderless / extended art varianty
}
# ---------------------------------------------------------------


def fetch_page(url, params):
    """Jeden dotaz na Scryfall. Pri 429 pocka a zkusi to znovu."""
    delay = 5
    for attempt in range(6):
        resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", delay))
            print(f"    429 od Scryfall, cekam {wait}s "
                  f"(pokus {attempt + 1}/6)...")
            time.sleep(wait)
            delay = min(delay * 2, 60)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError("Scryfall odmita odpovidat. Zkus to za par minut.")


def fetch_all_prints():
    """Stahne vsechny common paper printy, serazene od nejstarsiho."""
    params = {
        "q": QUERY,
        "order": "released",
        "dir": "asc",
        "unique": "prints",
    }
    url = API
    prints = []
    page = 1

    while url:
        data = fetch_page(url, params if url == API else None)
        prints.extend(data["data"])
        print(f"  strana {page}: +{len(data['data'])} printu "
              f"(celkem {len(prints)})")

        url = data.get("next_page") if data.get("has_more") else None
        page += 1
        time.sleep(REQUEST_DELAY)

    return prints


def load_prints(force_refresh=False):
    """Vrati raw data ze Scryfall. Pouzije lokalni cache, kdyz je cerstva."""
    if not force_refresh and os.path.exists(CACHE_FILE):
        age_days = (time.time() - os.path.getmtime(CACHE_FILE)) / 86400
        if age_days < CACHE_MAX_DAYS:
            with open(CACHE_FILE, encoding="utf-8") as f:
                prints = json.load(f)
            print(f"Pouzivam cache {CACHE_FILE} "
                  f"({len(prints)} printu, stari {age_days:.1f} dne).")
            print("Kdyz chces stahnout znovu: python3 "
                  "build_pauper_queue.py --refresh\n")
            return prints

    print("Stahuji Pauper-legal common printy ze Scryfall...")
    prints = fetch_all_prints()
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(prints, f, ensure_ascii=False)
    return prints


def face_block(face):
    """Sestavi textovy blok jedne strany karty."""
    lines = [face.get("name", "")]
    if face.get("mana_cost"):
        lines.append(face["mana_cost"])
    if face.get("type_line"):
        lines.append(face["type_line"])
    if face.get("oracle_text"):
        lines.append(face["oracle_text"])
    if face.get("flavor_text"):
        lines.append(face["flavor_text"])
    return "\n".join(lines)


def card_text(card):
    """Cely textovy blok karty. Osetruje oboustranne a split karty."""
    faces = card.get("card_faces")
    if faces and len(faces) > 1:
        # u DFC/split doplnime chybejici type_line z hlavni urovne
        blocks = []
        for f in faces:
            merged = dict(f)
            merged.setdefault("type_line", card.get("type_line", ""))
            blocks.append(face_block(merged))
        return "\n//\n".join(blocks)
    return face_block(card if not faces else {**faces[0], **{
        "name": card["name"],
        "type_line": card.get("type_line", faces[0].get("type_line", "")),
    }})


def get_uris(card):
    """Vrati slovnik s URL obrazku. Osetruje oboustranne karty."""
    if "image_uris" in card:
        return card["image_uris"]
    if card.get("card_faces") and "image_uris" in card["card_faces"][0]:
        return card["card_faces"][0]["image_uris"]
    return None


def get_image(card):
    """URL cele karty. 'large' je JPEG 672x936."""
    uris = get_uris(card)
    if not uris:
        return None
    return uris.get("large") or uris.get("normal")


def get_art(card):
    """URL samotneho artworku - pouzijeme na rozmazane pozadi."""
    uris = get_uris(card)
    if not uris:
        return None
    return uris.get("art_crop")


def build_queue(prints):
    """Sestavi frontu podle zvoleneho MODE a vyradi nechtene sety."""
    seen = {}
    out = []
    dropped = {}

    def drop(reason):
        dropped[reason] = dropped.get(reason, 0) + 1

    for card in prints:
        if card.get("set_type") in SKIP_SET_TYPES:
            drop(f"set_type: {card['set_type']}")
            continue
        if card.get("set", "").lower() in SKIP_SETS:
            drop(f"set: {card['set'].upper()}")
            continue
        if SKIP_PROMO_PRINTS and card.get("promo"):
            drop("promo print")
            continue
        hit = SKIP_PROMO_TYPES.intersection(card.get("promo_types") or [])
        if hit:
            drop(f"promo_type: {sorted(hit)[0]}")
            continue

        # pozor: snow basics maji "Basic Snow Land \u2014 Forest"
        tl = card.get("type_line", "")
        if SKIP_BASIC_LANDS and tl.startswith("Basic") and "Land" in tl:
            drop("basic land")
            continue

        img = get_image(card)
        if not img:
            drop("bez obrazku")
            continue

        # klic pro deduplikaci; u "prints" nededuplikujeme vubec
        if MODE == "cards":
            key = card.get("oracle_id")
        elif MODE == "art":
            key = card.get("illustration_id") or card.get("id")
        else:
            key = None

        if key is not None:
            if key in seen:
                continue  # uz mame starsi verzi
            seen[key] = True

        out.append({
            "oracle_id": card.get("oracle_id"),
            "scryfall_id": card["id"],
            "name": card["name"],
            "set": card["set"].upper(),
            "set_name": card["set_name"],
            "set_type": card.get("set_type", ""),
            "collector_number": card.get("collector_number", ""),
            "released_at": card["released_at"],
            "mana_cost": card.get("mana_cost", ""),
            "type_line": card.get("type_line", ""),
            "oracle_text": card.get("oracle_text", ""),
            "flavor_text": card.get("flavor_text", ""),
            "text_block": card_text(card),
            "artist": card.get("artist", ""),
            "image_url": img,
            "art_url": get_art(card),
            "scryfall_uri": card["scryfall_uri"],
        })

    queue = sorted(out, key=lambda c: (c["released_at"], c["set"], c["name"]))
    for i, card in enumerate(queue):
        card["index"] = i
    return queue, dropped


def build_posts(queue, size=CAROUSEL_SIZE):
    """Rozseka frontu na carousely. Nikdy nemicha sety dohromady."""
    posts = []
    current_set = None
    batch = []

    def flush():
        if batch:
            posts.append({
                "post_index": len(posts),
                "set": batch[0]["set"],
                "set_name": batch[0]["set_name"],
                "released_at": batch[0]["released_at"],
                "cards": list(batch),
            })
            batch.clear()

    for card in queue:
        if card["set"] != current_set:
            flush()
            current_set = card["set"]
        batch.append(card)
        if len(batch) == size:
            flush()
    flush()

    return posts


def main():
    force = "--refresh" in sys.argv
    prints = load_prints(force_refresh=force)
    print(f"\nK dispozici {len(prints)} printu celkem.")
    print(f"Rezim: {MODE}. Sestavuji frontu...")

    queue, dropped = build_queue(prints)
    posts = build_posts(queue)

    with open("pauper_queue.json", "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)
    with open("pauper_posts.json", "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)

    if dropped:
        print("\nVyrazeno:")
        for reason, count in sorted(dropped.items(), key=lambda x: -x[1]):
            print(f"  {count:6d}  {reason}")
        print(f"  {sum(dropped.values()):6d}  celkem")

    full = sum(1 for p in posts if len(p["cards"]) == CAROUSEL_SIZE)
    years = len(posts) / (POSTS_PER_DAY * 365.25)

    print(f"\nHotovo:")
    print(f"  {len(queue):6d} karet      -> pauper_queue.json")
    print(f"  {len(posts):6d} carouselu  -> pauper_posts.json")
    print(f"         z toho {full} plnych po {CAROUSEL_SIZE}, "
          f"{len(posts) - full} neuplnych (konce setu)")
    print(f"\n  Pri {POSTS_PER_DAY} postech denne: {years:.1f} let\n")

    print("Prvni 3 carousely:")
    for post in posts[:3]:
        names = ", ".join(c["name"] for c in post["cards"])
        print(f"  #{post['post_index']}  [{post['set']}] "
              f"{post['released_at']}  ({len(post['cards'])}x)")
        print(f"      {names}")

    print("\nUkazka textoveho bloku prvni karty:")
    print("  " + queue[0]["text_block"].replace("\n", "\n  "))


if __name__ == "__main__":
    main()
