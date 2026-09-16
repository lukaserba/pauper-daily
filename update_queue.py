#!/usr/bin/env python3
"""
Mesicni aktualizace fronty.

Pravidlo: co uz vyslo, je zamrzle. Prepocitava se jen budoucnost.

  - nova karta v setu, ktery jeste nevysel  -> zaradi se chronologicky,
                                               rozvrh se posune
  - nova karta v setu, ktery uz vysel       -> jen se zapise do logu,
                                               rozvrh se nemeni
  - karta uz neni Pauper-legal (ban)        -> vyradi se z budoucnosti,
                                               z minulosti se nemaze

Pouziti:
    python3 update_queue.py              # aktualizuje ze Scryfall
    python3 update_queue.py --dry-run    # jen ukaze, co by se stalo
    python3 update_queue.py --cached     # pracuje z cache, nesaha na Scryfall

Vstup:  pauper_posts.json, state.json
Vystup: prepsany pauper_queue.json + pauper_posts.json
        update_log.json  (historie vsech aktualizaci)
"""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_pauper_queue as cfg

LOG_FILE = "update_log.json"


def load(name, default=None):
    try:
        with open(name, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        if default is None:
            sys.exit(f"CHYBA: chybi {name}. Spust nejdriv "
                     f"build_pauper_queue.py")
        return default


def save(name, data):
    with open(name, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    dry = "--dry-run" in sys.argv
    cached = "--cached" in sys.argv

    old_posts = load("pauper_posts.json")
    state = load("state.json", default={"next_post": 0})
    next_post = state["next_post"]

    # --- co uz vyslo: zamrzle, nesaha se na to ---------------------
    published = old_posts[:next_post]
    future = old_posts[next_post:]
    published_ids = {c["scryfall_id"] for p in published for c in p["cards"]}
    published_sets = {c["set"] for p in published for c in p["cards"]}
    future_ids = {c["scryfall_id"] for p in future for c in p["cards"]}

    print(f"Stav: {len(published)} postu uz venku, "
          f"{len(future)} naplanovanych.")
    if published_sets:
        print(f"Publikovane sety: {len(published_sets)} "
              f"(naposledy {published[-1]['set']})")

    # --- svezi data ze Scryfall -----------------------------------
    raw = cfg.load_prints(force_refresh=not cached)
    queue, _ = cfg.build_queue(raw)
    fresh_ids = {c["scryfall_id"] for c in queue}

    # --- co je nove -----------------------------------------------
    added, missed = [], []
    for card in queue:
        if card["scryfall_id"] in published_ids:
            continue
        if card["scryfall_id"] in future_ids:
            continue
        if card["set"] in published_sets:
            missed.append(card)      # set uz vysel, rozvrh nemenime
        else:
            added.append(card)       # zaradi se do budoucnosti

    # --- co zmizelo (ban, delisting) ------------------------------
    removed = [c for p in future for c in p["cards"]
               if c["scryfall_id"] not in fresh_ids]
    removed_ids = {c["scryfall_id"] for c in removed}

    gone_published = [c for p in published for c in p["cards"]
                      if c["scryfall_id"] not in fresh_ids]

    print(f"\nZmeny:")
    print(f"  +{len(added):4d} novych karet do budoucich postu")
    print(f"  -{len(removed):4d} karet vyrazeno z budoucich postu")
    print(f"   {len(missed):4d} novych karet v jiz publikovanych setech "
          f"(jen log)")
    if gone_published:
        print(f"   {len(gone_published):4d} jiz publikovanych karet "
              f"uz neni legalnich (historie se nemeni)")

    if not added and not removed:
        print("\nNic k prepocitani. Rozvrh zustava.")
        return

    # --- prepocet budoucnosti -------------------------------------
    keep = [c for c in queue
            if c["scryfall_id"] not in published_ids
            and c["scryfall_id"] not in removed_ids
            and c["set"] not in published_sets]
    keep.sort(key=lambda c: (c["released_at"], c["set"], c["name"]))

    new_future = cfg.build_posts(keep)
    new_posts = published + new_future
    for i, post in enumerate(new_posts):
        post["post_index"] = i
    for i, card in enumerate(keep):
        card["index"] = len(published_ids) + i

    shift = len(new_posts) - len(old_posts)
    print(f"\nRozvrh: {len(old_posts)} -> {len(new_posts)} postu "
          f"({shift:+d})")
    if added:
        print("Prvni nove zarazene karty:")
        for c in added[:8]:
            print(f"   [{c['set']}] {c['released_at'][:10]}  {c['name']}")

    if dry:
        print("\n--dry-run: nic se neulozilo.")
        return

    save("pauper_posts.json", new_posts)
    save("pauper_queue.json",
         [c for p in new_posts for c in p["cards"]])

    log = load(LOG_FILE, default=[])
    log.append({
        "when": datetime.now().isoformat(timespec="seconds"),
        "published_posts": len(published),
        "posts_before": len(old_posts),
        "posts_after": len(new_posts),
        "added": [{"set": c["set"], "name": c["name"],
                   "id": c["scryfall_id"]} for c in added],
        "removed": [{"set": c["set"], "name": c["name"],
                     "id": c["scryfall_id"]} for c in removed],
        "missed_published_sets": [
            {"set": c["set"], "name": c["name"],
             "id": c["scryfall_id"]} for c in missed],
        "no_longer_legal_but_published": [
            {"set": c["set"], "name": c["name"]} for c in gone_published],
    })
    save(LOG_FILE, log)

    print(f"\nUlozeno. Historie v {LOG_FILE}.")
    print("Nezapomen prehnat build_schedule.py a nahrat novou tabulku.")


if __name__ == "__main__":
    main()
