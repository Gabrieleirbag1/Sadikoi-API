# VoteMe-API

[![Tests](https://github.com/Gabrieleirbag1/Sadikoi-API/actions/workflows/tests.yml/badge.svg)](https://github.com/Gabrieleirbag1/Sadikoi-API/actions/workflows/tests.yml)
## Security / anti-abuse

- **Rate limiting**: Flask-Limiter (in memory, single process) – see `src/security.py` and the `@limiter.limit` decorators in `src/app.py`. Over-limit requests get a JSON `429` with `Retry-After`.
- **Captcha**: Cloudflare Turnstile on login, register and forgot-password. Put the secret in `src/.turnstile.secrets` as `TURNSTILE_SECRET_KEY=...` (the test secret `1x0000000000000000000000000000000AA` always passes in dev).
- **Client IP**: `ProxyFix` trusts one proxy hop. Run Flask on `127.0.0.1` behind Apache; never expose it directly. An example vhost with timeouts, size limits and mod_evasive is in `deploy/apache-sadikoi.conf`.
- **Debug mode**: off unless `FLASK_DEBUG=1`. Never set it in production.
- **CORS / Socket.IO origins**: `ALLOWED_ORIGINS` in `src/config.py`.
- Volumetric DDoS (L3/L4) cannot be absorbed by the server itself: put Cloudflare (or your host's DDoS filtering) in front. With Cloudflare, read the client IP from `CF-Connecting-IP` instead of `X-Forwarded-For`.

## Admin local

Interface d'administration (Flask-Admin) **réservée au poste de dev**, dans `src/admin/` : dashboard, utilisateurs (désactiver / réactiver), suggestions, rapports de bugs (statut), et un menu *Base de données* qui affiche toutes les tables en lecture seule.

```bash
pip install -r requirements-dev.txt
python src/admin                    # http://127.0.0.1:8090/admin/  (options : --port, --db chemin/vers.db)
```

- Langue : sélecteur EN / FR dans la barre de navigation (mémorisé dans la session admin, sinon langue du navigateur, sinon français). Les textes de l'admin sont dans `src/admin/i18n.py` (source anglaise + dictionnaire `FR`) ; les libellés Flask-Admin viennent de ses catalogues via Flask-Babel.
- Secret d'accès : `ADMIN_SECRET=...` dans `src/.admin.secrets` (gitignoré). Généré automatiquement au premier lancement s'il manque ; le changer déconnecte les sessions admin. 5 essais par minute.
- Process séparé, jamais importé par `src/app.py` ; il refuse d'écouter ailleurs que sur `127.0.0.1` / `localhost`. Ne pas l'exposer derrière Apache.
- Désactiver un compte = `users.deleted = True` + `session_version` incrémentée : l'utilisateur est déconnecté immédiatement et ne peut plus se connecter.

## Migrations de la base

Le schéma est géré par des migrations (Flask-Migrate / Alembic), comme `makemigrations` / `migrate` dans Django. Les fichiers sont dans `migrations/versions/` et se commitent avec le changement de `models.py`.

```bash
python src/manage.py migrate                         # appliquer les migrations en attente (premier lancement, après un pull, en prod)
python src/manage.py makemigrations "add user bio"   # après une modif de models.py : génère la migration (à relire !)
python src/manage.py rollback                        # annuler la dernière migration
python src/manage.py showmigrations                  # historique + révision actuelle de la base
python src/manage.py makemigrations --check          # échoue si models.py a changé sans migration
```

- Toutes les commandes acceptent `--db chemin/vers.db` (par défaut `instance/data-local.db`).
- L'API ne crée plus les tables (`db.create_all()` supprimé) : au démarrage elle affiche une erreur si des migrations sont en attente.
- Une base créée avant les migrations (sans table `alembic_version`) est reconnue automatiquement au premier `migrate` : marquée `0001_initial`, puis seules les migrations suivantes s'appliquent (équivalent de `--fake-initial`).
- `0001_initial` ne peut pas être annulée (elle supprimerait toutes les tables).
- SQLite ne sait pas modifier une colonne : les migrations générées utilisent le mode *batch* (la table est recréée). Relire chaque fichier généré, surtout les renommages (détectés comme suppression + ajout).
- `tests/test_migrations.py` vérifie que les migrations produisent exactement le schéma de `models.py` : la CI échoue si une migration manque.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest                              # whole suite (~10 s, no network, no real email)
python -m pytest tests/test_chat.py -k expired  # a subset
python -m pytest --cov=src --cov-report=term-missing
```

- One file per domain in `tests/`: auth/register/login, auth security (devices, OTP, password reset), session guard, groups, chat, questions & votes, feedback, security (rate limits, headers, CORS), Socket.IO, unit tests.
- The app runs on a throw-away SQLite file in a temp directory; the schema is recreated for every test. `instance/` and `uploads/` are never touched.
- Everything external is faked by autouse fixtures in `tests/conftest.py`: emails (`externals.emails`, `externals.reset_links`), Turnstile (`externals.captcha_success`), Socket.IO emits (`externals.events`) and the question pool.
- Rate limiting is off by default; mark a test with `@pytest.mark.ratelimit` to run it against the real limiter.
- Data is built with `tests/factories.py` (`make_user`, `make_group`, `make_question(days_ago=...)`, `make_vote`...) and the `world` fixture (admin, member, outsider, other group). `login_as(user)` returns an authenticated client.
- `@pytest.mark.xfail(strict=True)` marks a **known defect** of the API with the expected (correct) behaviour: fixing the code turns the test into an error until the marker is removed.
- `tests/test_zz_route_coverage.py` fails if a route is never exercised, so new endpoints need a test.
- **CI**: `.github/workflows/tests.yml` runs the suite on every pull request to `main` and every push to `main`, and fails below 85 % coverage. No secret is needed.

# 7 défauts réels détectés (marqués xfail(strict) avec le comportement attendu)

  1. Doublon email/username à l'inscription : renvoie 500 au
     lieu d'un 4xx (2 tests).
  2. verify-device sans user_info : plante en 500
     (AttributeError).
  3. Création de groupe sans description : 500 (len(None) dans
     le validateur).
  4. promote d'un utilisateur inconnu : 500 (.id sur None).
  5. Invitations expirées : une fois la première expirée,
     chaque appel recrée un jeton (first() renvoie toujours
     l'ancienne ligne).
  6. assign_items : prend la 2e question la plus récente de
     tous les groupes, pas du groupe concerné. C'est le plus
     sérieux, car il peut attribuer ou rater des items.