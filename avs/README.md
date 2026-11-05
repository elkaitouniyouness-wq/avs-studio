# AI Video Automation Studio

Plateforme PWA (installable sur Android / iPhone) qui automatise la production de vidéos YouTube :
**sujet → script IA → voix réelle → médias → montage FFmpeg → sous-titres → SEO → miniature → contrôle qualité → validation → publication YouTube.**

## État réel de cette version (à lire)

| Élément | Statut |
|---|---|
| Moteur de montage FFmpeg (9:16, 16:9, 1:1, sous-titres arabes/latins, musique avec ducking, normalisation) | ✅ **Testé pour de vrai** (3 formats, médias synthétiques) |
| Logique pure (formats, budgets de mots, parsing IA, SEO, sous-titres) | ✅ Testée |
| API FastAPI, pipeline, scheduler, YouTube, file RQ | ⚠️ **Écrits et compilés, jamais exécutés** (PyPI bloqué dans l'environnement de développement). Un test d'intégration complet est fourni (`backend/tests/test_api.py`) : lancez-le (voir ci-dessous) |
| Frontend Next.js | ⚠️ **Jamais compilé** (npm bloqué). Lancez `npm run build` ; des petites erreurs de typage/syntaxe sont possibles |
| Appels réels Anthropic / Google TTS / Pexels / YouTube | ⚠️ **Jamais effectués** (aucune clé, pas de réseau) |

**Première chose à faire sur votre serveur :** `docker compose run --rm api pytest -q` puis un essai de bout en bout avec vos clés.

## Fonctionnalités livrées

- PWA mobile-first, FR / AR (RTL) / EN, mode clair/sombre, installable, coquille hors-ligne.
- Création de vidéo : niche, idées, sujet, durée (8 s → 10 min ou personnalisée), format, résolution, style, voix (genre, style, vitesse, **échantillon audio**), profils (Shorts rapides, Documentaire, Faits étonnants, Vidéo éducative) modifiables/enregistrables.
- Script IA structuré (hook, scènes, CTA), relecture IA, liste des **affirmations à vérifier**, édition manuelle avant production.
- **Option 100 % gratuite (palier gratuit Google Gemini, clé sur aistudio.google.com/apikey, sans carte d'après la doc Google)** : scripts/SEO via Gemini et voix via Gemini TTS, avec une seule clé. Quotas limités et conditions susceptibles de changer : vérifiez ai.google.dev/pricing. Sur le palier gratuit, Google peut utiliser vos contenus pour améliorer ses produits. Non testé contre l'API réelle.
- Voix **réelle** : Gemini TTS (si clé) → Google Cloud TTS (Chirp3-HD) → repli voix par genre → repli OpenAI TTS (si clé). Aucun audio simulé.
- Médias libres de droits via Pexels (clips verticaux/horizontaux), sans doublons ; carte de remplacement **signalée** si rien trouvé ; remplacement manuel d'une image/clip depuis le téléphone.
- Montage FFmpeg : mouvement de caméra sur images, fondus, sous-titres synchronisés brûlés + fichier SRT, musique de fond (dossier `music/`) réduite sous la voix, volume normalisé (-16 LUFS), MP4.
- SEO : 3 titres, description, hashtags, tags, catégorie, nom de fichier, idée + miniature 1280×720 lisible sur mobile. Limites YouTube appliquées (titre ≤ 100, tags ≤ 500 car., etc.).
- Contrôle qualité avant publication : fichier, pistes, format, silence, durée, synchro, métadonnées, médias, doublons, affirmations à vérifier, licences (avertissements).
- Publication YouTube officielle (OAuth 2.0 + Data API v3) : upload **résumable/reprenable**, miniature, public/privé/non répertorié, programmation, plusieurs chaînes, anti-doublon, mode manuel (défaut) ou automatique soumis aux règles.
- Automatisations : planifications (heure, jours, nombre de vidéos, niche, langue, profil, chaîne, confidentialité, comportement en cas d'erreur), exécutées par un vrai scheduler + worker. **Arrêt d'urgence** immédiat.
- Coûts : estimation avant lancement, coût réel estimé par étape, budgets par vidéo / jour / mois avec arrêt automatique.
- Sécurité : cookie httpOnly + SameSite, mots de passe bcrypt, clés API et jetons YouTube **chiffrés (Fernet)**, jamais renvoyés au navigateur, limitation des tentatives de connexion, aucun mot de passe Google demandé.

## Non implémenté (volontairement ou faute de pouvoir le tester)

- Génération d'images/vidéos par IA générative (seulement stock Pexels + cartes). Prévu comme fournisseur additionnel.
- Clonage vocal : **désactivé** (non implémenté).
- Voix Darija native : aucun fournisseur grand public n'en propose ; le texte est rédigé en darija mais lu par une voix arabe standard.
- Transitions : fondus uniquement (pas de fondus enchaînés), pas d'effets sonores.
- Statistiques YouTube (vues, abonnés) : nécessitent YouTube Analytics API, non incluses. Le tableau de bord affiche l'activité de production et les coûts.
- Notifications : dans l'application (rafraîchies toutes les 10 s). Pas de push système.
- Éditeur de workflow : modules activables/désactivables (mode expert) avec ordre fixe, pas de canevas glisser-déposer.
- Vérification factuelle : l'IA liste les affirmations à vérifier ; aucune vérification web automatique. La détection de droits d'auteur est limitée à des avertissements.
- Compte de démonstration : aucun (pas d'environnement de démo sécurisé).

## Architecture

```
PWA Next.js ──(même origine /api)──► FastAPI ──► PostgreSQL
                                        │  └───► Redis ──► worker RQ (pipeline : IA, TTS, Pexels, FFmpeg, upload)
                                        └ scheduler (planifications)        médias : volume Docker /data/media
Services externes : Anthropic · Google TTS (+ OpenAI TTS) · Pexels · YouTube Data API v3 (OAuth)
```

Le téléphone ne fait **aucun calcul lourd** : il pilote un serveur qui tourne en continu.

```
backend/app/{main,pipeline,scheduler,models,security,options,costs,keys,queue}.py
backend/app/services/{llm,tts,media,render,thumb,trends,youtube}.py
backend/tests/   frontend/app/*  frontend/lib/*  frontend/public/{manifest.webmanifest,sw.js,icons}
```

## Installation locale rapide

```bash
cp .env.example .env
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # → APP_ENCRYPTION_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(48))"                                  # → APP_SECRET_KEY
# éditez .env : ADMIN_EMAIL, ADMIN_PASSWORD, clés API, COOKIE_SECURE=false en local http
docker compose up --build        # http://localhost:3000
```

Dans l'appli : **Réglages → Clés API** (ou `.env`), puis **Chaînes YouTube → Connecter**, puis **Créer**.

Tests : `docker compose run --rm api pytest -q` (les tests d'API simulent Anthropic/TTS/Pexels ; FFmpeg est réel).

## Installer l'application sur le téléphone (PWA)

Nécessite une adresse **HTTPS** (voir `docs/DEPLOIEMENT.md`).
- **Android (Chrome)** : menu ⋮ → « Installer l'application ».
- **iPhone (Safari)** : bouton Partager → « Sur l'écran d'accueil ».

Voir aussi : `docs/DEPLOIEMENT.md` (serveur, clés, OAuth YouTube, coûts) et `docs/DEPANNAGE.md`.
