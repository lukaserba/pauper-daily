#!/usr/bin/env python3
"""
Krok 2: vyrenderuje dalsi carousel z fronty + slozi caption.

Pouziti:
    pip install requests pillow
    python3 render_post.py            # vyrenderuje dalsi post ve fronte
    python3 render_post.py --peek     # jen ukaze, co je na rade, nic nedela
    python3 render_post.py --index 42 # vyrenderuje konkretni post
    python3 render_post.py --no-advance   # vyrenderuje, ale neposune frontu

Vstup:  pauper_posts.json   (z build_pauper_queue.py)
Vystup: out/post_00042/slide_1.jpg ... slide_5.jpg
        out/post_00042/caption.txt
Stav:   state.json          (kde jsme ve fronte)
        skip_dates.json     (dny, kdy bot mlci)
"""

import argparse
import io
import json
import os
import sys
from datetime import date

import requests
from PIL import Image, ImageFilter, ImageEnhance, ImageDraw

# ---------------------------------------------------------------
# NASTAVENI
CANVAS_W, CANVAS_H = 1080, 1350     # Instagram 4:5
CARD_HEIGHT_RATIO = 0.90            # jak vysoka je karta vuci platnu
BLUR_RADIUS = 40                    # rozmazani pozadi
BG_DARKEN = 0.55                    # 1.0 = beze zmeny, niz = tmavsi
CORNER_RADIUS_MM = 3.0              # skutecny radius MTG karty
CARD_WIDTH_MM = 63.0                # sirka MTG karty

# Alpha byla rezana jinou matrici a ma vyrazne kulatejsi rohy nez
# vsechny ostatni sety. Zdroje se lisi v absolutnich cislech, shoduji
# se ale na zhruba dvojnasobku. Uprav podle toho, jak to vypada.
CORNER_RADIUS_BY_SET = {
    "LEA": 6.0,
}
SUPERSAMPLE = 4                     # vyhlazeni masky rohu
JPEG_QUALITY = 92
INCLUDE_FLAVOR = True               # flavor text v captionu
MAX_CAPTION = 2200                  # tvrdy limit Instagramu

DISCLAIMER = (
    "Unofficial Fan Content permitted under the Wizards of the Coast "
    "Fan Content Policy. Not approved/endorsed by Wizards. Portions of the "
    "materials used are property of Wizards of the Coast. "
    "\u00a9Wizards of the Coast LLC."
)

HASHTAGS = (
    "#mtg #mtgpauper #pauper #magicthegathering #commons #mtgcommunity "
    "#mtgart #pauperedh #mtgcz"
)
# ---------------------------------------------------------------

HEADERS = {"User-Agent": "PauperDailyBot/1.0 (kontakt@example.com)"}
HERE = os.path.dirname(os.path.abspath(__file__))


def path(name):
    return os.path.join(HERE, name)


def load_json(name, default=None):
    try:
        with open(path(name), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        if default is None:
            sys.exit(f"CHYBA: chybi {name}. Spust nejdriv build_pauper_queue.py")
        return default


def save_json(name, data):
    with open(path(name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def download(url):
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content)).convert("RGB")


def rounded_mask(size, radius_mm=CORNER_RADIUS_MM):
    """Maska se zaoblenymi rohy v pomeru skutecne MTG karty.
    Kresli se zvetsene a zmensi se zpatky -> hladke hrany."""
    w, h = size
    radius = int(w * radius_mm / CARD_WIDTH_MM)
    big = (w * SUPERSAMPLE, h * SUPERSAMPLE)
    mask = Image.new("L", big, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, big[0] - 1, big[1] - 1],
        radius=radius * SUPERSAMPLE, fill=255)
    return mask.resize(size, Image.LANCZOS)


def make_background(art):
    """Rozmazany, ztmaveny artwork roztazeny pres cele platno."""
    # zvetsit tak, aby pokryl platno, a orezat na stred
    scale = max(CANVAS_W / art.width, CANVAS_H / art.height) * 1.15
    bg = art.resize((int(art.width * scale), int(art.height * scale)),
                    Image.LANCZOS)
    left = (bg.width - CANVAS_W) // 2
    top = (bg.height - CANVAS_H) // 2
    bg = bg.crop((left, top, left + CANVAS_W, top + CANVAS_H))
    bg = bg.filter(ImageFilter.GaussianBlur(BLUR_RADIUS))
    return ImageEnhance.Brightness(bg).enhance(BG_DARKEN)


def make_slide(card):
    """Slozi jeden slide: karta vysazena na 1080x1350."""
    front = download(card["image_url"])

    if card.get("art_url"):
        try:
            canvas = make_background(download(card["art_url"]))
        except Exception:
            canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), (18, 18, 20))
    else:
        canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), (18, 18, 20))

    # karta na vysku, pomer zustava zachovany
    target_h = int(CANVAS_H * CARD_HEIGHT_RATIO)
    target_w = int(front.width * target_h / front.height)
    if target_w > CANVAS_W * 0.94:          # pojistka pro atypicke pomery
        target_w = int(CANVAS_W * 0.94)
        target_h = int(front.height * target_w / front.width)
    front = front.resize((target_w, target_h), Image.LANCZOS)

    x = (CANVAS_W - target_w) // 2
    y = (CANVAS_H - target_h) // 2
    radius_mm = CORNER_RADIUS_BY_SET.get(card.get("set", ""), CORNER_RADIUS_MM)
    canvas.paste(front, (x, y), rounded_mask(front.size, radius_mm))
    return canvas


def build_caption(post):
    """Sestavi caption. Kdyz je moc dlouhy, postupne ubira."""
    header = f"{post['set_name']} ({post['set']}) \u2014 {post['released_at'][:4]}"

    def assemble(with_flavor, with_tags):
        parts = [header, ""]
        for i, card in enumerate(post["cards"], 1):
            block = card["text_block"]
            if not with_flavor and card.get("flavor_text"):
                block = block.replace("\n" + card["flavor_text"], "")
            parts.append(f"{i}/ {block}")
            parts.append("")
        if with_tags:
            parts.append(HASHTAGS)
            parts.append("")
        parts.append(DISCLAIMER)
        return "\n".join(parts)

    for flavor, tags in ((INCLUDE_FLAVOR, True), (False, True), (False, False)):
        text = assemble(flavor, tags)
        if len(text) <= MAX_CAPTION:
            return text, len(text)

    # posledni zachrana: jen nazvy karet
    names = "\n".join(f"{i}/ {c['name']}  {c['mana_cost']}"
                      for i, c in enumerate(post["cards"], 1))
    text = f"{header}\n\n{names}\n\n{DISCLAIMER}"
    return text, len(text)


def should_skip():
    skip = load_json("skip_dates.json", default=[])
    today = date.today().isoformat()
    return today in skip


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=int, help="konkretni post_index")
    ap.add_argument("--peek", action="store_true", help="jen ukaz, nic nedelej")
    ap.add_argument("--no-advance", action="store_true",
                    help="vyrenderuj, ale neposunuj frontu")
    args = ap.parse_args()

    posts = load_json("pauper_posts.json")
    state = load_json("state.json", default={"next_post": 0})

    if args.index is None and should_skip():
        print(f"{date.today().isoformat()} je v skip_dates.json \u2014 bot mlci.")
        return

    idx = args.index if args.index is not None else state["next_post"]
    if idx >= len(posts):
        print("Fronta je u konce. Spust build_pauper_queue.py znovu "
              "\u2014 mezitim vysly nove sety.")
        return

    post = posts[idx]
    caption, clen = build_caption(post)

    print(f"Post #{idx}  [{post['set']}] {post['set_name']}  "
          f"{post['released_at']}  ({len(post['cards'])} karet)")
    for i, card in enumerate(post["cards"], 1):
        print(f"   {i}. {card['name']}")
    print(f"Caption: {clen} znaku z {MAX_CAPTION}")

    if args.peek:
        print("\n--- caption ---")
        print(caption)
        return

    outdir = path(os.path.join("out", f"post_{idx:05d}"))
    os.makedirs(outdir, exist_ok=True)

    for i, card in enumerate(post["cards"], 1):
        slide = make_slide(card)
        dest = os.path.join(outdir, f"slide_{i}.jpg")
        slide.save(dest, "JPEG", quality=JPEG_QUALITY, optimize=True)
        print(f"   ulozeno {os.path.basename(dest)}")

    with open(os.path.join(outdir, "caption.txt"), "w", encoding="utf-8") as f:
        f.write(caption)

    if args.index is None and not args.no_advance:
        state["next_post"] = idx + 1
        save_json("state.json", state)
        print(f"\nFronta posunuta na #{state['next_post']}.")

    print(f"Hotovo: {outdir}")


if __name__ == "__main__":
    main()
