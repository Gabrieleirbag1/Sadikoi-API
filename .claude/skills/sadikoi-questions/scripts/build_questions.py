#!/usr/bin/env python3
"""Convertit des questions Sadikoi au format compact en JSON pour l'API, et vérifie les règles.

Format compact (voir SKILL.md) :
    # theme_id|Nom FR|Name EN
    s H|Question en français ?|Question in English?
    s! B|...   (! = enableSelfVote false)

Usage :
    build_questions.py lot.txt [autre.txt ...] --out questions_x.json
        [--existing src/data/questions_1000_v2.json ...] [--start-id N]
        [--themes src/data/question_themes_x.json] [--check-only]

Sort avec le code 1 et la liste des problèmes si une règle est violée ; rien n'est écrit dans ce cas.
"""
import argparse
import collections
import json
import os
import re
import sys

ITEMS = {
    "L": ("cape_leader", "Cape du Leader", "Leader's Cape"),
    "H": ("bonnet_honte", "Bonnet de la Honte", "Dunce Cap"),
    "T": ("masque_traitre", "Masque du Traître", "Traitor's Mask"),
    "B": ("bouclier_loyal", "Bouclier de la Loyauté", "Shield of Loyalty"),
    "C": ("torche_chaos", "Torche du Chaos", "Torch of Chaos"),
    "E": ("etoile_destin", "Étoile du Destin", "Star of Destiny"),
    "G": ("lunettes_genie", "Lunettes du Génie", "Genius Glasses"),
    "K": ("cle_secrets", "Clé des Secrets", "Key of Secrets"),
    "P": ("coeur_passion", "Cœur de la Passion", "Heart of Passion"),
    "D": ("couronne_drama", "Couronne du Drama", "Drama Queen Crown"),
    "V": ("trophee_vice", "Trophée du Vice", "Trophy of Vice"),
    "M": ("micro_verite", "Micro de la Vérité", "Mic of Truth"),
}
ITEMS_BY_ID = {v[0]: v for v in ITEMS.values()}
TYPES = {"s": "solo", "d": "duo", "r": "ranking", "c": "scenario", "t": "trap", "y": "dynamique"}
# enableSelfVote, enableMultipleVoting, voteNumberLimit
VOTE = {
    "solo": (True, False, 1), "scenario": (True, False, 1), "trap": (True, False, 1),
    "dynamique": (True, False, 1), "duo": (False, True, 2), "ranking": (True, True, 0),
}
TARGET_MIX = {"solo": .25, "duo": .20, "ranking": .10, "scenario": .15, "trap": .15, "dynamique": .15}
THEMES_OFF_BY_DEFAULT = {"hot"}

# Calques de l'anglais repérés dans les anciens lots.
CALQUES = [
    (r"Qui est vraiment|vraiment celui|vraiment celle", "calque de « who really »"),
    (r"susceptible de", "calque de « most likely to » (dire « a le plus de chances de »)"),
    (r"\((vraiment|pour de vrai)\)", "« (vraiment) » en fin de phrase"),
    (r"formerait le duo", "gabarit « formerait le duo » (dire « Quel duo… »)"),
    (r"tremblerait le plus|transpirerait le plus", "calque (dire « flipperait »)"),
    (r"[ÉE]pic[ée]", "« épicé » pour « spicy »"),
]


def parse(paths):
    questions, themes, errors = [], {}, []
    for path in paths:
        theme = None
        with open(path, encoding="utf-8") as f:
            for n, raw in enumerate(f, 1):
                line = raw.rstrip("\n")
                where = f"{os.path.basename(path)}:{n}"
                if not line.strip():
                    continue
                if line.startswith("#"):
                    parts = line.lstrip("#").strip().split("|")
                    if len(parts) != 3 or not re.fullmatch(r"[a-z0-9_]+", parts[0]):
                        errors.append(f"{where} thème mal formé (attendu « # id|Nom FR|Name EN ») : {line}")
                        continue
                    theme = dict(zip(("id", "fr", "en"), (p.strip() for p in parts)))
                    themes[theme["id"]] = theme
                    for pattern, why in CALQUES:
                        if re.search(pattern, theme["fr"]):
                            errors.append(f"{where} nom de thème : {why} : {theme['fr']}")
                    continue
                parts = line.split("|")
                if len(parts) != 3:
                    errors.append(f"{where} attendu 3 champs séparés par | : {line}")
                    continue
                head, fr, en = (p.strip() for p in parts)
                m = re.fullmatch(r"([sdrcty])(!?)\s+(\S+)", head)
                if not m:
                    errors.append(f"{where} en-tête invalide « {head} » (ex. « s H », « s! B »)")
                    continue
                if theme is None:
                    errors.append(f"{where} question avant toute ligne de thème")
                    continue
                code, no_self, item = m.groups()
                item_def = ITEMS.get(item) or ITEMS_BY_ID.get(item)
                if not item_def:
                    errors.append(f"{where} item inconnu « {item} »")
                    continue
                qtype = TYPES[code]
                self_vote, multi, limit = VOTE[qtype]
                questions.append({
                    "content": {"fr": fr, "en": en},
                    "type": qtype,
                    "theme": dict(theme),
                    "enableSelfVote": self_vote and not no_self,
                    "enableMultipleVoting": multi,
                    "voteNumberLimit": limit,
                    "canWrite": False,
                    "item_name": dict(zip(("id", "fr", "en"), item_def)),
                    "_where": where,
                })
    return questions, themes, errors


def normalize(s):
    return re.sub(r"\W+", " ", s.lower()).strip()


def check(questions, existing):
    errors, warnings = [], []
    for q in questions:
        fr, en, w = q["content"]["fr"], q["content"]["en"], q["_where"]
        if re.search(r"\w/\w|\(e\)|·", fr) or re.search(r"\b(il|elle)/(il|elle)\b", fr):
            errors.append(f"{w} écriture inclusive : {fr}")
        if re.search(r"\bsi ils?\b", fr, re.I):
            errors.append(f"{w} « si il(s) » au lieu de « s'il(s) » : {fr}")
        for pattern, why in CALQUES:
            if re.search(pattern, fr):
                errors.append(f"{w} {why} : {fr}")
        if re.search(r"[^\s«][?!:;]", fr):
            errors.append(f"{w} FR : il manque une espace avant ? ! : ; -> {fr}")
        if re.search(r"\s[?!:;]", en):
            errors.append(f"{w} EN : espace avant la ponctuation -> {en}")
        if '"' in fr:
            errors.append(f"{w} FR : guillemets droits, utiliser « » -> {fr}")
        end = "." if q["type"] == "ranking" else "?"
        if not fr.endswith(end) or not en.endswith(end):
            errors.append(f"{w} une question {q['type']} doit finir par « {end} » : {fr} || {en}")
        if "  " in fr or "  " in en:
            errors.append(f"{w} double espace")

    seen = {}
    for q in existing:
        for lang in ("fr", "en"):
            seen.setdefault(normalize(q["content"][lang]), f"déjà dans les fichiers existants (id {q['question_id']})")
    for q in questions:
        for lang in ("fr", "en"):
            key = normalize(q["content"][lang])
            if key in seen:
                errors.append(f"{q['_where']} doublon {lang.upper()}, {seen[key]} : {q['content'][lang]}")
            else:
                seen[key] = f"déjà en {q['_where']}"

    by_theme = collections.defaultdict(list)
    for q in questions:
        by_theme[q["theme"]["id"]].append(q)
    for tid, qs in by_theme.items():
        starts = collections.Counter(" ".join(q["content"]["fr"].split()[:3]) for q in qs)
        for start, count in starts.items():
            if count > 3:
                errors.append(f"thème {tid} : {count} questions commencent par « {start} » (max 3)")

    total = len(questions)
    if total >= 20:
        mix = collections.Counter(q["type"] for q in questions)
        for t, target in TARGET_MIX.items():
            share = mix[t] / total
            if abs(share - target) > 0.08:
                warnings.append(f"répartition : {t} = {share:.0%} (conseillé ~{target:.0%})")
        items = collections.Counter(q["item_name"]["id"] for q in questions)
        missing = [i for i in ITEMS_BY_ID if i not in items]
        if missing and total >= 50:
            warnings.append(f"items jamais utilisés : {', '.join(missing)}")
    return errors, warnings


def load_json(path, default):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="fichiers .txt au format compact")
    ap.add_argument("--out", help="fichier JSON de questions à écrire")
    ap.add_argument("--existing", action="append", default=[], help="JSON de questions existant (doublons + numérotation)")
    ap.add_argument("--start-id", type=int, help="premier question_id (par défaut : max des --existing + 1)")
    ap.add_argument("--themes", help="fichier de thèmes à créer ou compléter")
    ap.add_argument("--check-only", action="store_true", help="vérifier sans rien écrire")
    args = ap.parse_args()

    existing = [q for path in args.existing for q in load_json(path, [])]
    questions, themes, errors = parse(args.inputs)
    check_errors, warnings = check(questions, existing)
    errors += check_errors

    start = args.start_id or (max((q["question_id"] for q in existing), default=0) + 1)
    for i, q in enumerate(questions):
        q["question_id"] = start + i

    print(f"{len(questions)} questions, {len(themes)} thèmes, ids {start} à {start + len(questions) - 1}")
    print("types :", dict(collections.Counter(q["type"] for q in questions)))
    print("items :", dict(collections.Counter(q["item_name"]["id"] for q in questions)))
    for w in warnings:
        print("ATTENTION", w)
    for e in errors:
        print("ERREUR", e)
    if errors:
        print(f"\n{len(errors)} erreur(s) : rien n'a été écrit.")
        sys.exit(1)
    if args.check_only:
        print("OK (vérification seule)")
        return
    if not args.out:
        ap.error("--out est requis (ou --check-only)")

    for q in questions:
        del q["_where"]
    ordered = [{k: q[k] for k in ("question_id", "content", "type", "theme", "enableSelfVote",
                                   "enableMultipleVoting", "voteNumberLimit", "canWrite", "item_name")}
               for q in questions]
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(ordered, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("écrit :", args.out)

    if args.themes:
        current = load_json(args.themes, {})
        added = [tid for tid in themes if tid not in current]
        for tid in added:
            current[tid] = {**themes[tid], "checked": tid not in THEMES_OFF_BY_DEFAULT}
        with open(args.themes, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"thèmes : {args.themes} ({len(added)} ajouté(s){': ' + ', '.join(added) if added else ''})")


if __name__ == "__main__":
    main()
