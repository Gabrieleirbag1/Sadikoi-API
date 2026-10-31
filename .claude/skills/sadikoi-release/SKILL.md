---
name: sadikoi-release
description: Écrit les notes de version de Sadikoi, dans le style des releases déjà publiées. Produit la release GitHub de l'API (Sadikoi-API), celle de l'appli (Sadikoi, Angular/Android) et les notes Google Play en anglais et en français. Utilise ce skill dès que l'utilisateur demande une release, un changelog, des notes de version, un « What's Changed », le texte « Nouveautés » du Play Store, ou veut préparer/publier une nouvelle version (1.0.x), même s'il ne cite qu'un des deux dépôts ou seulement Google Play.
---

# Releases Sadikoi

Sadikoi tient dans deux dépôts GitHub publics, voisins sur le disque :

| Dépôt | Chemin local | Tags |
|---|---|---|
| `Gabrieleirbag1/Sadikoi-API` (Flask) | `Sadikoi-API/` | `1.0.0`, `1.0.1`… (sans `v`) |
| `Gabrieleirbag1/Sadikoi` (Angular + Capacitor Android) | `../Sadikoi/` depuis l'API | idem |

Les numéros de version des deux dépôts sont indépendants : chacun prend la version suivante de son propre dernier tag.

Une demande de « release » donne en général **trois textes** :
1. la release GitHub de l'API ;
2. la release GitHub de l'appli ;
3. les notes Google Play (« Nouveautés de cette version »), en anglais et en français.

Si l'utilisateur n'en demande qu'une partie, ne fais que celle-là.

## Méthode

1. **Relire le style actuel.** `gh` n'est pas installé : passe par l'API publique de GitHub. Les 3 dernières releases suffisent.
   ```bash
   for r in Sadikoi-API Sadikoi; do
     curl -s "https://api.github.com/repos/Gabrieleirbag1/$r/releases?per_page=3" | python3 -c "
   import json,sys
   for x in json.load(sys.stdin): print('##', x['tag_name']); print(x['body']); print('-----')"
   done
   ```
   Si le style a changé depuis ce skill, suis les releases publiées, pas ce fichier.
2. **Lister les changements depuis le dernier tag** de chaque dépôt :
   ```bash
   git fetch --tags -q
   git log --oneline <dernier_tag>..HEAD
   git status --short   # du travail non commité n'est pas dans la release : signale-le
   ```
   Les messages de commit sont courts et parfois approximatifs (« stules », « enhance(fix) »). Pour chaque commit dont l'effet n'est pas évident, lis le diff (`git show --stat <sha>`, puis le code). Une ligne de release décrit **ce que l'utilisateur voit**, pas le nom du commit.
3. **Écrire les deux releases GitHub** (format ci-dessous).
4. **Écrire les notes Google Play** à partir de la release de l'appli, plus les changements de l'API visibles par l'utilisateur (ex. notifications). Vérifie la longueur :
   ```bash
   python3 .claude/skills/sadikoi-release/scripts/check_play_notes.py notes_play.txt
   ```
5. **Signaler ce qui reste à faire** pour publier : la version Android dans `../Sadikoi/android/app/build.gradle` (`versionName` = nouvelle version, `versionCode` + 1) si elle n'est pas déjà montée, et la création des tags. Ne crée ni tag ni release toi-même sans qu'on te le demande : c'est public.

## Format des releases GitHub

En anglais, toujours ce squelette :

```markdown
# Sadikoi-API 1.0.3

## What's Changed
* Message notifications are only sent to members who already answered the question of the day
* Fix the question of the day being created several times when members open the group at the same moment
* Add tests for the message notifications and the question creation

**Full Changelog**: https://github.com/Gabrieleirbag1/Sadikoi-API/compare/1.0.2...1.0.3
```

- Titre : `# Sadikoi-API <version>` ou `# Sadikoi <version>` (l'appli s'appelle juste « Sadikoi »).
- Une puce `*` par changement, une seule phrase, sans point final.
- Verbes et tournures déjà utilisés :
  - `New …` pour une fonctionnalité (« New countdown to the next question of the day »),
  - `Fix …` pour un bug, décrit par le symptôme (« Fix being logged out when opening the app without network »),
  - pour une amélioration, la phrase décrit le nouveau comportement (« Vote bubbles on mobile: tap to select, long press to see the profile »),
  - `Add tests for …` en fin de liste quand il y a des tests.
- Préfixe `Zone: …` quand ça aide à situer (« Duo questions: … », « Chat: … », « Vote bubbles: … »).
- L'explication du pourquoi va entre parenthèses, seulement si elle est utile (« (you can't vote for yourself, so a group of 2 couldn't answer them) »).
- Code et noms techniques entre backticks, seulement pour l'API (`create-review-account`, `next_question_at`, migration `0006_…`).
- Ordre : nouveautés visibles d'abord, puis améliorations, puis corrections, puis tests/refactor.
- Fusionne les commits qui font une seule chose (feature + i18n + fix du même sujet = une puce). N'invente rien et ne gonfle pas : pas d'adjectifs marketing.
- Lien final : `**Full Changelog**: https://github.com/Gabrieleirbag1/<repo>/compare/<ancien_tag>...<nouveau_tag>`.

## Format Google Play

Les notes vont dans « Nouveautés de cette version » de la Play Console, une balise par langue :

```
<en-US>
• New countdown to the next question of the day, which then shows up by itself
• Fix tapping a notification from another group
</en-US>
<fr-FR>
• Nouveau compte à rebours avant la prochaine question du jour, qui s'affiche ensuite toute seule
• Correction : toucher la notif d'un autre groupe l'ouvre bien
</fr-FR>
```

- **500 caractères max par langue** (balises non comprises) : passe le script de vérification.
- Code de langue Play : `en-US` (pas `en-EN`, qui n'existe pas) et `fr-FR`. Si l'utilisateur a mis l'anglais britannique par défaut dans la Play Console, ce sera `en-GB`.
- Public : les joueurs, pas des devs. Rien de technique (pas de tests, d'API, de refactor, de verrou…). Ne garde que ce qu'on voit ou sent dans l'appli, 5 à 7 puces `•`, les plus parlantes d'abord.
- Le français s'écrit comme on parle entre potes (tutoiement, « notif », « direct »), comme le reste de l'appli. Ce n'est pas une traduction mot à mot de l'anglais : adapte chaque phrase.
- Corrections en fin de liste : « Fix … » en anglais, « Correction : … » en français.

## Rendu

Donne les trois textes dans des blocs de code séparés, prêts à copier-coller, chacun avec son titre (dépôt + version, ou « Google Play »). Ajoute en dessous la liste courte de ce qui reste à faire (version Android, tags, travail non commité).
