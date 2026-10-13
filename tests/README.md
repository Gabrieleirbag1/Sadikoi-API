# Lancer les tests du backend

Toutes les commandes se lancent depuis `Sadikoi-API/` avec le venv du projet.

```bash
cd Sadikoi-API
source venv/bin/activate          # ou préfixer par venv/bin/python -m
pip install -r requirements-dev.txt   # une seule fois (pytest + pytest-cov)
```

> `pytest.ini` définit `addopts = -q` (sortie compacte par défaut). Conséquence : `-v` seul **s'annule** avec `-q`.
> Utilisez `-vv`, ou `-o addopts=""` pour repartir d'une config vierge.

## 1. Lancer la suite

| Besoin | Commande |
|---|---|
| Tout lancer (sortie compacte) | `python -m pytest` |
| Verbose : un test par ligne (PASSED / FAILED) | `python -m pytest -vv` |
| Verbose sans le `-q` du `pytest.ini` | `python -m pytest -o addopts="" -v` |
| Très silencieux (juste le résumé) | `python -m pytest -qq` |
| S'arrêter au premier échec | `python -m pytest -x` |
| S'arrêter après N échecs | `python -m pytest --maxfail=3` |
| Relancer uniquement les tests tombés la dernière fois | `python -m pytest --lf` |
| Tombés d'abord, puis le reste | `python -m pytest --ff` |
| Afficher les `print()` / logs en direct | `python -m pytest -s` |

## 2. Cibler des tests

### Par fichier

| Domaine | Commande |
|---|---|
| Inscription / connexion / compte | `python -m pytest tests/test_auth_register_login.py` |
| Sécurité auth (OTP, appareils, mot de passe oublié, signalement) | `python -m pytest tests/test_auth_security.py` |
| Garde de session (`before_request`) | `python -m pytest tests/test_session_guard.py` |
| Groupes (CRUD, rôles, invitations) | `python -m pytest tests/test_groups.py` |
| Chat | `python -m pytest tests/test_chat.py` |
| Questions & votes | `python -m pytest tests/test_questions_votes.py` |
| Feedback (bugs / suggestions) | `python -m pytest tests/test_feedback.py` |
| Sécurité (rate-limit, en-têtes, CORS, taille) | `python -m pytest tests/test_security.py` |
| Socket.IO | `python -m pytest tests/test_sockets.py` |
| Unitaires (fonctions pures, modèles) | `python -m pytest tests/test_unit.py` |
| Couverture des routes (fin de suite) | `python -m pytest tests/test_zz_route_coverage.py` |

Plusieurs fichiers : `python -m pytest tests/test_chat.py tests/test_groups.py`

### Par classe ou par test précis

```bash
python -m pytest tests/test_groups.py::TestPromote
python -m pytest tests/test_groups.py::TestPromote::test_cannot_promote_yourself
python -m pytest "tests/test_groups.py::TestCreateGroup::test_invalid_payloads[change3]"   # cas paramétré
```

### Par mot-clé (`-k`, sur le nom du fichier / classe / test)

```bash
python -m pytest -k "vote"                       # tout ce qui contient "vote"
python -m pytest -k "expired or previous_day"    # OU
python -m pytest -k "vote and not written"       # ET / NON
python -m pytest tests/test_chat.py -k "non_member"
```

### Par marqueur

```bash
python -m pytest -m ratelimit                    # uniquement les tests de rate-limit (limiteur réel)
python -m pytest -m "not ratelimit"              # tout sauf ceux-là
```

## 3. Comprendre ce qui est lancé

| Besoin | Commande |
|---|---|
| Lister les tests sans les exécuter | `python -m pytest --collect-only -q` |
| Lister ceux d'un fichier / d'un filtre | `python -m pytest tests/test_chat.py --collect-only -q` |
| Voir les 10 tests les plus lents | `python -m pytest --durations=10` |
| Raisons des `xfail` / `skip` | `python -m pytest -rxs` |
| Résumé complet (échecs, xfail, skip, erreurs) | `python -m pytest -ra` |
| Liste des marqueurs et fixtures | `python -m pytest --markers` / `python -m pytest --fixtures` |

## 4. Déboguer un échec

| Besoin | Commande |
|---|---|
| Traceback court | `python -m pytest --tb=short` |
| Traceback ligne unique | `python -m pytest --tb=line` |
| Traceback complet avec variables locales | `python -m pytest --tb=long -l` |
| Aucune trace (juste la liste) | `python -m pytest --tb=no` |
| Ouvrir `pdb` au premier échec | `python -m pytest -x --pdb` |
| Dernier échec uniquement, très détaillé | `python -m pytest --lf -vv -l --tb=long` |
| Voir le test comme s'il n'était pas `xfail` | `python -m pytest --runxfail tests/test_groups.py -k unknown_user` |

## 5. Couverture de code

```bash
python -m pytest --cov=src                                   # résumé par fichier
python -m pytest --cov=src --cov-report=term-missing         # + lignes non couvertes
python -m pytest --cov=src --cov-report=html                 # rapport dans htmlcov/index.html
python -m pytest --cov=src --cov-fail-under=85               # échoue sous 85 %
python -m pytest tests/test_chat.py --cov=src/chat.py --cov-report=term-missing
```

## 6. Défauts connus (`xfail`)

Les tests `@pytest.mark.xfail(strict=True)` décrivent le **comportement attendu** d'un bug encore présent dans l'API.

```bash
python -m pytest -rx                       # liste les xfail et la raison
python -m pytest --runxfail -k "duplicate" # voir l'échec réel
```

Quand le bug est corrigé, le test devient une **erreur** (`XPASS(strict)`) : retirer alors le décorateur `xfail`.

## 7. Recettes rapides

```bash
python -m pytest -x -vv --lf                       # boucle de correction : je relance ce qui a cassé, détaillé
python -m pytest -m ratelimit -vv                  # vérifier les limites de débit
python -m pytest -q --cov=src --cov-report=term-missing --cov-fail-under=85   # check « CI »
python -m pytest tests/test_security.py tests/test_session_guard.py -vv        # toute la partie sécurité
```

## 8. Où ça tourne

- Base SQLite **temporaire**, recréée à chaque test : `instance/` et `uploads/` ne sont jamais touchés.
- Réseau, emails, Turnstile et Socket.IO sont simulés (fixture `externals` dans `conftest.py`).
- Aucune variable d'environnement n'est nécessaire ; `FLASK_DEBUG` n'a pas d'effet sur les tests.
