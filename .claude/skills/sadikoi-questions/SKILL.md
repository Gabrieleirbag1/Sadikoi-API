---
name: sadikoi-questions
description: Génère, réécrit ou corrige des questions bilingues (FR/EN) pour l'appli Sadikoi, où chaque jour le groupe vote pour un de ses membres. Produit un fichier JSON compatible avec l'API (src/data/questions*.json, question_themes*.json). Utilise ce skill dès que l'utilisateur veut de nouvelles questions, un nouveau lot, un nouveau thème, des questions plus hot/drôles/gênantes, corriger la traduction ou le français des questions existantes, ou ajouter des items/objets aux questions, et aussi quand il donne directement une liste de thèmes à ajouter (« ajoute les thèmes nostalgie, avenir… ») — même s'il ne dit pas « skill » ni « JSON ».
---

# Questions Sadikoi

Sadikoi est une appli sociale entre potes. Chaque jour, une question est posée à tout le groupe et chacun vote pour un ou plusieurs membres. La personne qui reçoit le plus de votes gagne l'objet (item) lié à la question. Le public : des adultes francophones (France) de 18 à 35 ans, qui se connaissent bien.

Le premier lot généré avait un français « traduit de l'anglais » (« Qui est vraiment celui/celle qui… », thème « Épicé » pour *Spicy*, etc.). Ce skill existe surtout pour éviter ça : **le français s'écrit en premier, comme à l'oral entre potes ; l'anglais est une adaptation, pas l'inverse.**

## Méthode

1. **Repérer l'existant.** Les questions sont dans `src/data/` (`questions.json` est chargé par l'API via `src/utils.py`, les autres fichiers sont des lots). Lis un échantillon du lot le plus récent pour caler le ton, et note les thèmes déjà présents dans `question_themes*.json`.
2. **Écrire les questions au format compact** (voir plus bas) dans un fichier `.txt` du scratchpad. Ce format est 3 fois plus court que le JSON et le script calcule tout le reste (ids, règles de vote, noms des items), donc moins d'erreurs.
3. **Convertir et vérifier** avec le script fourni :
   ```bash
   python3 .claude/skills/sadikoi-questions/scripts/build_questions.py lot.txt \
     --out src/data/questions_<nom>.json \
     --existing src/data/questions_v5.json \
     --themes src/data/question_themes_<nom>.json
   ```
   - `--existing` (répétable) : fichiers déjà en place. Le script refuse les doublons et numérote à la suite (ou `--start-id N`).
   - Ne renumérote jamais les questions existantes : `question_id` est stocké en base et `src/builder.py` s'en sert pour retrouver le texte. Quand on supprime un thème, les trous dans les ids restent.
   - `--themes` : fichier de thèmes à créer ou compléter. Sans ça, l'API refuse les nouveaux thèmes (`src/group.py`).
   - Le script s'arrête sur la première passe si une règle est violée et liste chaque problème avec sa ligne. Corrige le `.txt` et relance jusqu'à ce qu'il passe.
4. **Relire à froid** quelques questions de chaque thème avec la grille de la fin de ce fichier : le script attrape les erreurs mécaniques, pas une phrase maladroite.
5. **Ne pas écraser** un fichier existant sans que l'utilisateur le demande : crée un nouveau fichier et dis-lui comment le brancher (`src/utils.py` charge `questions.json` et `question_themes.json`).

## Thèmes proposés par l'utilisateur

Quand l'utilisateur donne une liste de thèmes (« ajoute ces thèmes : nostalgie, avenir, travail… »), crée-les directement avec leurs questions, sans lui demander de confirmer ni lui proposer d'options. C'est lui qui choisit les thèmes ; la règle « réutilise un id existant » de la section 4 ne sert qu'à éviter les collisions d'id.

- **L'id existe déjà** dans un `question_themes*.json` (comparaison en snake_case sans accent) : ajoute les nouvelles questions sous ce même id, avec les mêmes noms FR/EN. L'API identifie un thème par son id, donc deux thèmes avec le même id entreraient en collision.
- **L'id n'existe pas** : crée le thème avec le mot de l'utilisateur (au singulier, en snake_case, sans accent : « entreprises » → `entreprise`), même s'il ressemble à un thème existant (avenir / futur, travail / boulot). Lis alors les questions du thème voisin et choisis un angle différent : par exemple futur = célébrité, Mars, prédictions ; avenir = vie d'adulte concrète (appart, mariage, enfants, impôts).
- **« a/b »** (« ecole/etudes ») désigne un seul thème qui couvre les deux sujets : prends l'id existant s'il y en a un, sinon le premier mot.
- Le nom EN ne doit pas reprendre celui d'un thème existant (futur s'appelle déjà *Future*, donc avenir devient *What's Next*).
- Volume par défaut : 40 questions par thème, sauf si l'utilisateur donne un autre chiffre.
- Mets tous les thèmes dans un seul `.txt` et un seul lot. Le fichier `--themes` contient aussi les thèmes réutilisés, pour que le lot soit complet à lui seul.
- Dans le compte rendu, sépare les thèmes créés des thèmes complétés, et signale chaque thème proche d'un thème existant.

## Format compact

```
# soiree|Soirée|Party
s H|Qui serait le premier à vomir en soirée ?|Who'd be the first to throw up at a party?
d P|Quel duo finirait par se pécho après une soirée trop arrosée ?|Which two would end up hooking up after a few too many drinks?
s! B|Qui viendrait te chercher à 4h du mat sans poser de questions ?|Who'd come pick you up at 4 a.m., no questions asked?
r V|Classe le groupe du plus sobre au plus bourré en fin de soirée.|Rank the group from soberest to drunkest by the end of the night.
```

- `# id|Nom FR|Nom EN` ouvre un thème ; les lignes suivantes en font partie.
- Ligne de question : `<type><!?> <item>|<français>|<anglais>`.
- Types : `s` solo, `d` duo, `r` ranking, `c` scenario, `t` trap, `y` dynamique.
- `!` après le type passe `enableSelfVote` à `false`, quand voter pour soi n'a pas de sens (« Qui *te* dit la vérité… »). Les duos sont déjà à `false`.
- Item : la lettre du tableau des items (ou son id complet).

## 1. Langue

### Français : à faire
- Registre oral, familier mais correct : « en soirée », « bourré », « galérer », « flipper », « se griller », « se taper la honte », « balancer », « pécho », « radin », « relou ».
- Des phrases courtes et directes, une idée par question.
- Garder en anglais les mots que les Français utilisent tels quels : crush, date, ghoster, stalker, cringe, flex, red flag, toxic, story, DM, like, follower, screen, nude, body count, plan cul, after, bad buzz, binge-watcher, prank, fake, random, wtf, spoiler, gaming, hot.
- Références françaises : Koh-Lanta, Top Chef, Pékin Express, Les Marseillais, Qui veut gagner des millions, Carrefour, Leboncoin, Blablacar, Pronote, le bac, la fac, l'apéro, le brunch du dimanche.

### Français : à éviter
- **Les calques de l'anglais**, qui trahissent une traduction :
  - « Qui est vraiment celui/celle qui… » (*who really…*) → « Dans le groupe, c'est qui qui… ? », ou simplement « Qui… ? »
  - « Qui est le plus susceptible de… » (*most likely to*) → « Qui a le plus de chances de… », « Qui serait le premier à… »
  - « Qui tremblerait / transpirerait le plus » → « Qui flipperait le plus », « Qui serait le plus mal »
  - « Qui serait le plus choquant dans… » → un verbe concret : « Qui aurait les pires révélations au « Je n'ai jamais » ? »
  - « (vraiment) » ou « (pour de vrai) » en fin de phrase
  - Les thèmes traduits mot à mot : « Hot » ou « Coquin », pas « Épicé »
- **L'écriture inclusive** (« celui/celle », « le/la », « (e) », « il/elle », « ·e ») : illisible à l'oral. Préfère une tournure sans genre : un verbe (« Qui passe sa vie à… »), un mot épicène (« la personne la plus… », « le boulet », « la balance », « la star »). Sinon, masculin générique.
- **Les gabarits répétés** : dans un même thème, pas plus de 3 questions qui commencent par les mêmes 3 mots. Les pistes du tableau des types sont des idées, pas des modèles à recopier.

### Exemples (mauvais → bon)
- « Qui est vraiment celui/celle qui stalke le plus sur Instagram ? » → « Qui passe ses soirées à stalker des inconnus sur Insta ? »
- « Qui formerait le duo le plus commère du groupe ? » → « Quel duo balancerait tous les potins du groupe en moins d'une heure ? »
- « Qui formerait le duo qui finirait ensemble un soir de soirée arrosée ? » → « Quel duo finirait par se pécho après une soirée trop arrosée ? »
- « Qui est le plus intelligent du groupe (vraiment) ? » → « Qui est le vrai cerveau de la bande ? »
- « Qui est vraiment le/la fayot(e) du groupe ? » → « Qui était le chouchou des profs ? »
- « Et si tout le monde recevait le screenshot de toutes tes conversations, qui transpirerait le plus ? » → « Si toutes vos conversations étaient balancées dans le groupe, qui serait le plus dans la merde ? »

### Anglais
- Anglais américain courant, ton entre amis : "Who'd be the first to…", "Who's most likely to…", "Which two…".
- Adapter les références : Top Chef → MasterChef, Koh-Lanta → Survivor, Pékin Express → The Amazing Race, Carrefour → Walmart, Leboncoin → Facebook Marketplace, € → $.
- Pas de calque du français non plus (pas de "Dunce Cap of Shame", pas de "a jerk like a table").

### Orthographe
- Français : espace avant `?`, `!`, `:`, `;` ; guillemets « » ; élisions correctes (« s'ils », jamais « si ils »).
- Anglais : pas d'espace avant la ponctuation ; guillemets droits "…".
- Les questions `ranking` finissent par un point (« … classe-nous. »), les autres par `?`.

## 2. Ton

- Fun, décalé, un peu gênant, révélateur de la personnalité.
- Des scénarios concrets : un lieu, un moment, un enjeu.
- Parfois incriminant, mais jamais méchant envers un physique, une origine, une religion ou une orientation sexuelle : le but est de rire ensemble, pas d'humilier quelqu'un.
- Le sexe et les questions osées sont autorisés (adultes), plutôt dans le thème `hot`.

Exemples du bon ton : « On doit tous faire un numéro dans un spectacle de talents : qui irait le plus loin ? », « Qui serait le pire coloc du groupe ? », « Qui se ferait éliminer en premier à Koh-Lanta ? », « Qui cache un secret que personne ici ne connaît ? »

## 3. Types de questions

Le type décrit la **mécanique de vote**, le thème décrit le **sujet** : ce sont deux choses indépendantes.

| type | code | Vote | Pistes de formulation FR |
|---|---|---|---|
| solo | `s` | 1 personne | « Qui serait le premier à… », « Qui a le plus de chances de… », « Qui ferait le pire… » |
| duo | `d` | 2 personnes | « Quel duo… », « Quels deux membres… », « Qui ferait la pire équipe pour… », « Quel binôme… » |
| ranking | `r` | classement de tous | « Classe le groupe du plus… au plus… », « Range tout le monde selon… », « Du… au…, classe-nous. » |
| scenario | `c` | 1 personne | « On part tous à… : qui… ? », « Le groupe est coincé dans… : qui… ? » |
| trap | `t` | 1 personne | « Qui oserait… », « Qui n'hésiterait pas à… », « Qui serait prêt à… », « Qui pourrait… sans remords ? » |
| dynamique | `y` | 1 personne | « Qui est le … de la bande ? », « Qui joue le rôle de… », « Dans le groupe, c'est qui qui… ? » |

Répartition conseillée : environ 25 % solo, 20 % duo, 10 % ranking, 15 % scenario, 15 % trap, 15 % dynamique.

**Types désactivés** : avant d'écrire, lis `DISABLED_QUESTION_TYPES` dans `src/question.py`. Un type qui y figure n'est jamais posé à un groupe (en ce moment `ranking`, faute d'interface de vote et de score). N'en génère pas et répartis sa part entre les autres types. L'avertissement « ranking = 0 % » du script est alors normal.

Chaque question doit se résoudre par un vote pour des membres du groupe. À éviter : les questions à deux réponses (« qui donne les ordres et qui obéit ? »), les questions oui/non et celles qui visent quelqu'un hors du groupe.

Règles de vote, appliquées par le script : solo, scenario, trap et dynamique → `enableSelfVote: true`, `enableMultipleVoting: false`, `voteNumberLimit: 1` ; duo → `false`, `true`, `2` ; ranking → `true`, `true`, `0` (illimité). `canWrite` vaut toujours `false` (`true` voudrait dire réponse libre en texte au lieu d'un vote, cf. `src/question.py`).

## 4. Thèmes

Un `id` en snake_case sans accent, un nom FR et un nom EN naturels. Le lot de référence est `questions_v5.json` (v4 + crado, ids 1 à 1320, sans complot). Ses thèmes : soiree, boulot, ecole, mechant, loisirs, et_si, hot (Hot / Spicy), voyage, argent, reseaux, amour, famille, survie, absurde, amitie, futur, bouffe, sport, secrets, nostalgie (Throwback), avenir (What's Next), travail (Jobs : tous les métiers, pas seulement le bureau), illegal (Illégal et dangereux / Living Dangerously), crado (Crado / Gross). Le thème complot a été retiré à la demande de l'utilisateur : ne le recrée pas sans qu'il le demande. Réutilise un id existant quand le sujet correspond, plutôt que d'en créer un quasi identique.

Dans le fichier de thèmes, `checked` indique si le thème est activé par défaut ; le script le met à `false` pour `hot` et à `true` pour les autres.

## 5. Items

Il y a exactement 12 items et le jeu en dépend (`item_name.id` est stocké en base). N'en invente pas et ne change pas leurs id. Le sens est volontairement large pour qu'un même objet couvre beaucoup de questions. Répartis-les à peu près équitablement ; `P` est souvent sous-représenté, pense à l'utiliser pour l'amour et la drague.

| code | id | fr | en | Pour quelles questions |
|---|---|---|---|---|
| L | cape_leader | Cape du Leader | Leader's Cape | chef, organisateur, celui qui décide |
| H | bonnet_honte | Bonnet de la Honte | Dunce Cap | gaffe, honte, échec, ridicule |
| T | masque_traitre | Masque du Traître | Traitor's Mask | trahison, mensonge, manipulation |
| B | bouclier_loyal | Bouclier de la Loyauté | Shield of Loyalty | fidélité, soutien, ami fiable |
| C | torche_chaos | Torche du Chaos | Torch of Chaos | bordel, folie, imprévisible |
| E | etoile_destin | Étoile du Destin | Star of Destiny | réussite, avenir, célébrité |
| G | lunettes_genie | Lunettes du Génie | Genius Glasses | intelligence, débrouillardise, talent |
| K | cle_secrets | Clé des Secrets | Key of Secrets | secrets, double vie, mystère |
| P | coeur_passion | Cœur de la Passion | Heart of Passion | amour, séduction, sexe |
| D | couronne_drama | Couronne du Drama | Drama Queen Crown | drama, ego, jalousie, réaction excessive |
| V | trophee_vice | Trophée du Vice | Trophy of Vice | excès, addictions, plaisirs coupables |
| M | micro_verite | Micro de la Vérité | Mic of Truth | franchise, cash, sans filtre |

## 6. Format JSON produit

Le script produit des entrées de cette forme, celle lue par `src/builder.py` :

```json
{
  "question_id": 1,
  "content": { "fr": "Qui serait le premier à vomir en soirée ?", "en": "Who'd be the first to throw up at a party?" },
  "type": "solo",
  "theme": { "id": "soiree", "fr": "Soirée", "en": "Party" },
  "enableSelfVote": true,
  "enableMultipleVoting": false,
  "voteNumberLimit": 1,
  "canWrite": false,
  "item_name": { "id": "bonnet_honte", "fr": "Bonnet de la Honte", "en": "Dunce Cap" }
}
```

Si l'utilisateur veut un JSON sans passer par le script (par exemple pour coller dans un autre outil), respecte exactement ces champs : l'API plante sur `item` au lieu de `item_name`, ou sur un `theme` sans `id`.

## 7. Relecture finale

Avant de rendre le lot, relis les questions et corrige celles où l'un de ces points est vrai :
1. Un Français de 25 ans ne dirait pas cette phrase à ses potes.
2. On dirait une traduction de l'anglais.
3. On ne peut pas y répondre en votant pour un membre (ou deux pour un duo).
4. L'anglais ne dit pas la même chose, ou sonne comme du français traduit.
5. La question ressemble trop à une question déjà présente dans le lot ou dans les fichiers existants (même idée reformulée).
