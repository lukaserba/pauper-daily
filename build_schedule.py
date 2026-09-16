#!/usr/bin/env python3
"""
Krok 1b: vyrobi planovaci tabulku pro Instagram.

Jeden list na kazdy rok (~33 listu). V kazdem roce:
  - harmonogram postu den po dni, 2x denne po 5 kartach
  - pod tim seznam karet, ktere jsme z tech setu vyradili a proc

Navic:
  - list "Prehled" se souhrnem
  - list "Vyrazene sety" s celymi sety, ktere do fronty nejdou

Pouziti:
    python3 -m pip install --user openpyxl
    python3 build_schedule.py

Vstup:  pauper_posts.json, pauper_queue.json, scryfall_raw.json
        (vsechny vyrobi build_pauper_queue.py)
Vystup: pauper_plan.xlsx
"""

import json
import os
import sys
from datetime import date, timedelta

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# ---------------------------------------------------------------
# NASTAVENI
START_DATE = date(2026, 10, 1)      # prvni den postovani
POST_TIMES = ["9:00", "19:00"]      # casy postu behem dne
OUTPUT = "pauper_plan.xlsx"
FONT = "Arial"
# ---------------------------------------------------------------

# barvy
HEAD_BG = PatternFill("solid", fgColor="1F3864")
HEAD_FG = Font(name=FONT, bold=True, color="FFFFFF", size=10)
POST_A = PatternFill("solid", fgColor="FFFFFF")
POST_B = PatternFill("solid", fgColor="EDF2F9")
DROP_BG = PatternFill("solid", fgColor="F2F2F2")
TITLE = Font(name=FONT, bold=True, size=13)
SUB = Font(name=FONT, bold=True, size=11, color="7F7F7F")
BODY = Font(name=FONT, size=10)
LINKF = Font(name=FONT, size=10, color="0563C1", underline="single")
THIN = Side(style="thin", color="D0D0D0")
BOX = Border(top=THIN, bottom=THIN, left=THIN, right=THIN)

COLS = ["Datum", "Den", "Cas", "Post", "Slide", "Set", "Karta",
        "Mana cost", "Typ", "Rok setu", "Scryfall"]
WIDTHS = [12, 6, 7, 8, 7, 8, 38, 16, 34, 10, 52, 30]
DAYS_CZ = ["Po", "Ut", "St", "Ct", "Pa", "So", "Ne"]

# Sekce vyrazenych karet zacina ve sloupci F, aby sedela pod
# harmonogramem: Set, Karta, Mana, Typ, Rok, Scryfall + Duvod navic.
DROP_COL0 = 6
DROP_HEADS = ["Set", "Karta", "Mana cost", "Typ", "Rok",
              "Scryfall", "Duvod"]
WRAP = Alignment(vertical="top", wrap_text=True)


def load(name):
    if not os.path.exists(name):
        sys.exit(f"CHYBA: chybi {name}. Spust nejdriv build_pauper_queue.py")
    with open(name, encoding="utf-8") as f:
        return json.load(f)


def schedule_slots(count):
    """Vrati [(datum, cas), ...] pro zadany pocet postu."""
    slots = []
    day = START_DATE
    i = 0
    while len(slots) < count:
        slots.append((day, POST_TIMES[i % len(POST_TIMES)]))
        i += 1
        if i % len(POST_TIMES) == 0:
            day += timedelta(days=1)
    return slots


def drop_reason(card, cfg):
    """Proc karta neni ve fronte. None = je ve fronte."""
    if card.get("set_type") in cfg.SKIP_SET_TYPES:
        return f"kategorie setu: {card['set_type']}"
    if card.get("set", "").lower() in cfg.SKIP_SETS:
        return "vyrazeny set"
    if cfg.SKIP_PROMO_PRINTS and card.get("promo"):
        return "promo print"
    hit = cfg.SKIP_PROMO_TYPES.intersection(card.get("promo_types") or [])
    if hit:
        return f"promo_type: {sorted(hit)[0]}"
    tl = card.get("type_line", "")
    if cfg.SKIP_BASIC_LANDS and tl.startswith("Basic") and "Land" in tl:
        return "basic land"
    if not cfg.get_image(card):
        return "bez obrazku na Scryfall"
    return None


def write_header(ws, row):
    for i, name in enumerate(COLS, 1):
        c = ws.cell(row=row, column=i, value=name)
        c.fill, c.font, c.border = HEAD_BG, HEAD_FG, BOX
        c.alignment = Alignment(horizontal="center", vertical="center")
    return row + 1


def build_year_sheet(wb, year, posts, drops):
    ws = wb.create_sheet(str(year))
    for i, w in enumerate(WIDTHS, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws["A1"] = f"Rok {year}"
    ws["A1"].font = TITLE
    sets = sorted({p["set"] for p in posts} |
                  {c["set"].upper() for c in drops})
    ws["A2"] = (f"{len(posts)} postu \u00b7 "
                f"{sum(len(p['cards']) for p in posts)} naplanovanych karet \u00b7 "
                f"{len(drops)} vyrazenych \u00b7 sety: {', '.join(sets)}")
    ws["A2"].font = BODY

    row = 4
    if posts:
        row = write_header(ws, row)
        ws.freeze_panes = ws.cell(row=row, column=1)

        for n, post in enumerate(posts):
            fill = POST_A if n % 2 == 0 else POST_B
            d, t = post["_date"], post["_time"]
            for slide, card in enumerate(post["cards"], 1):
                vals = [
                    d.strftime("%d.%m.%Y") if slide == 1 else "",
                    DAYS_CZ[d.weekday()] if slide == 1 else "",
                    t if slide == 1 else "",
                    post["post_index"] if slide == 1 else "",
                    slide,
                    card["set"],
                    card["name"],
                    card.get("mana_cost", ""),
                    card.get("type_line", ""),
                    card["released_at"][:4],
                    card.get("scryfall_uri", ""),
                ]
                for i, v in enumerate(vals, 1):
                    c = ws.cell(row=row, column=i, value=v)
                    c.fill, c.border = fill, BOX
                    c.font = LINKF if i == 11 and v else BODY
                    if i in (2, 3, 4, 5, 10):
                        c.alignment = Alignment(horizontal="center")
                    elif i in (7, 9):
                        c.alignment = WRAP
                if vals[-1]:
                    ws.cell(row=row, column=11).hyperlink = vals[-1]
                row += 1
    else:
        ws.cell(row=row, column=1,
                value="V tomto roce nevysel zadny set, ktery by se postoval.")
        ws.cell(row=row, column=1).font = BODY
        row += 1

    if not drops:
        return

    row += 2
    c = ws.cell(row=row, column=DROP_COL0, value="VYRAZENE KARTY")
    c.font = SUB
    row += 1
    for i, name in enumerate(DROP_HEADS):
        c = ws.cell(row=row, column=DROP_COL0 + i, value=name)
        c.fill, c.font, c.border = HEAD_BG, HEAD_FG, BOX
        c.alignment = Alignment(horizontal="center", vertical="center")
    row += 1

    for card in drops:
        vals = [card["set"].upper(), card["name"],
                card.get("mana_cost", ""), card.get("type_line", ""),
                card["released_at"][:4], card.get("scryfall_uri", ""),
                card["_reason"]]
        for i, v in enumerate(vals):
            col = DROP_COL0 + i
            c = ws.cell(row=row, column=col, value=v)
            c.fill, c.border = DROP_BG, BOX
            c.font = LINKF if i == 5 and v else BODY
            if i == 4:
                c.alignment = Alignment(horizontal="center")
            elif i in (1, 3, 6):
                c.alignment = WRAP
        if vals[5]:
            ws.cell(row=row, column=DROP_COL0 + 5).hyperlink = vals[5]
        row += 1


def build_overview(wb, by_year, n_sched, n_excl, n_raw, unknown):
    ws = wb.create_sheet("Prehled", 0)
    for i, w in enumerate([14, 14, 16, 16, 16, 16], 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws["A1"] = "Pauper Instagram \u2014 planovaci tabulka"
    ws["A1"].font = TITLE
    ws["A2"] = (f"Start {START_DATE.strftime('%d.%m.%Y')} \u00b7 "
                f"{len(POST_TIMES)} posty denne v {', '.join(POST_TIMES)} \u00b7 "
                f"5 karet v carouselu")
    ws["A2"].font = BODY
    ws["A3"] = "Data ze Scryfall, dotaz: legal:pauper r:c game:paper"
    ws["A3"].font = Font(name=FONT, size=9, italic=True, color="7F7F7F")

    # kontrola uplnosti
    ok = (n_sched + n_excl == n_raw) and not unknown
    ws["A5"] = "KONTROLA UPLNOSTI"
    ws["A5"].font = SUB
    checks = [
        ("Printu ze Scryfall", n_raw),
        ("Naplanovanych karet", n_sched),
        ("Vyrazenych karet", n_excl),
    ]
    row = 6
    for label, val in checks:
        ws.cell(row=row, column=1, value=label).font = BODY
        c = ws.cell(row=row, column=2, value=val)
        c.font, c.alignment = BODY, Alignment(horizontal="center")
        row += 1
    ws.cell(row=row, column=1, value="Rozdil").font = Font(name=FONT, bold=True)
    c = ws.cell(row=row, column=2, value=f"=B{row - 2}+B{row - 1}-B{row - 3}")
    c.font = Font(name=FONT, bold=True)
    c.alignment = Alignment(horizontal="center")
    ws.cell(row=row, column=3,
            value="OK - vsechny karty sedi" if ok
            else f"POZOR - {len(unknown)} karet bez znameho duvodu").font = (
        Font(name=FONT, bold=True, color="008000" if ok else "C00000"))

    row += 2
    head_row = row
    for i, name in enumerate(["Rok", "Postu", "Karet", "Vyrazeno",
                              "Prvni post", "Posledni post"], 1):
        c = ws.cell(row=row, column=i, value=name)
        c.fill, c.font, c.border = HEAD_BG, HEAD_FG, BOX
    row += 1
    first = row

    for year in sorted(by_year):
        posts, drops = by_year[year]
        vals = [year, len(posts), sum(len(p["cards"]) for p in posts),
                len(drops),
                posts[0]["_date"].strftime("%d.%m.%Y") if posts else "\u2014",
                posts[-1]["_date"].strftime("%d.%m.%Y") if posts else "\u2014"]
        for i, v in enumerate(vals, 1):
            c = ws.cell(row=row, column=i, value=v)
            c.font, c.border = BODY, BOX
            if i <= 4:
                c.alignment = Alignment(horizontal="center")
        row += 1

    last = row - 1
    ws.cell(row=row, column=1, value="CELKEM").font = Font(name=FONT, bold=True)
    for col in (2, 3, 4):
        L = get_column_letter(col)
        c = ws.cell(row=row, column=col, value=f"=SUM({L}{first}:{L}{last})")
        c.font = Font(name=FONT, bold=True)
        c.border = BOX
        c.alignment = Alignment(horizontal="center")
    ws.freeze_panes = ws.cell(row=head_row + 1, column=1)


def build_skipped_sets(wb, raw, cfg):
    """Cele sety, ktere do fronty vubec nejdou."""
    ws = wb.create_sheet("Vyrazene sety")
    for i, w in enumerate([10, 40, 14, 12, 40], 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws["A1"] = "Sety vyrazene jako celek"
    ws["A1"].font = TITLE
    ws["A2"] = ("Tyto sety se do harmonogramu nedostaly vubec. "
                "Uprava: SKIP_SETS / SKIP_SET_TYPES v build_pauper_queue.py")
    ws["A2"].font = BODY

    agg = {}
    for card in raw:
        code = card.get("set", "").lower()
        st = card.get("set_type")
        if st in cfg.SKIP_SET_TYPES:
            reason = f"kategorie: {st}"
        elif code in cfg.SKIP_SETS:
            reason = "na seznamu SKIP_SETS"
        else:
            continue
        key = (code.upper(), card.get("set_name", ""), card["released_at"][:4])
        agg.setdefault(key, [0, reason])
        agg[key][0] += 1

    row = 4
    for i, name in enumerate(["Kod", "Nazev setu", "Rok", "Karet", "Duvod"], 1):
        c = ws.cell(row=row, column=i, value=name)
        c.fill, c.font, c.border = HEAD_BG, HEAD_FG, BOX
    row += 1

    for (code, name, year), (count, reason) in sorted(
            agg.items(), key=lambda x: (-x[1][0], x[0][0])):
        for i, v in enumerate([code, name, year, count, reason], 1):
            c = ws.cell(row=row, column=i, value=v)
            c.font, c.border = BODY, BOX
            if i in (3, 4):
                c.alignment = Alignment(horizontal="center")
        row += 1
    ws.freeze_panes = ws.cell(row=5, column=1)


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import build_pauper_queue as cfg

    posts = load("pauper_posts.json")
    raw = load("scryfall_raw.json")

    slots = schedule_slots(len(posts))
    for post, (d, t) in zip(posts, slots):
        post["_date"], post["_time"] = d, t

    scheduled = {c["scryfall_id"] for p in posts for c in p["cards"]}

    # VSECHNY vyrazene karty, vcetne tech z celych vyrazenych setu
    drops_by_year = {}
    excluded = set()
    for card in raw:
        if card["id"] in scheduled:
            continue
        card["_reason"] = drop_reason(card, cfg) or "nezname"
        excluded.add(card["id"])
        drops_by_year.setdefault(card["released_at"][:4], []).append(card)

    by_year = {}
    for post in posts:
        by_year.setdefault(post["released_at"][:4], [[], []])[0].append(post)
    for year, drops in drops_by_year.items():
        by_year.setdefault(year, [[], []])[1] = sorted(
            drops, key=lambda c: (c["set"], c["name"]))

    # kontrola uplnosti
    unknown = [c for c in raw if c.get("_reason") == "nezname"]
    total = len(scheduled) + len(excluded)

    wb = Workbook()
    wb.remove(wb.active)

    for year in sorted(by_year):
        p, d = by_year[year]
        build_year_sheet(wb, year, p, d)
        print(f"  {year}: {len(p):4d} postu, {len(d):5d} vyrazenych karet")

    build_overview(wb, by_year, len(scheduled), len(excluded),
                   len(raw), unknown)
    build_skipped_sets(wb, raw, cfg)
    wb.save(OUTPUT)

    last = posts[-1]["_date"]
    print(f"\nHotovo: {OUTPUT}")
    print(f"  {len(posts)} postu, {len(by_year)} roku")
    print(f"  {START_DATE.strftime('%d.%m.%Y')} "
          f"\u2192 {last.strftime('%d.%m.%Y')}")
    print(f"\nKONTROLA UPLNOSTI:")
    print(f"  {len(scheduled):6d} naplanovanych")
    print(f"  {len(excluded):6d} vyrazenych")
    print(f"  {total:6d} soucet")
    print(f"  {len(raw):6d} printu ze Scryfall")
    if total == len(raw) and not unknown:
        print("  OK - kazdy print je bud naplanovany, nebo vyrazeny "
              "se znamym duvodem.")
    else:
        print(f"  POZOR: {len(raw) - total} printu chybi, "
              f"{len(unknown)} bez znameho duvodu.")
        for c in unknown[:10]:
            print(f"     {c['set'].upper()} {c['name']}")


if __name__ == "__main__":
    main()
