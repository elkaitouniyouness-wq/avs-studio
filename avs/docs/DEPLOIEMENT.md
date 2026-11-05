# Déploiement sur un serveur

## 1. Serveur
- VPS Linux (Ubuntu 22.04/24.04), **4 vCPU / 8 Go RAM / 80+ Go disque** recommandés pour du 1080p ; 2 vCPU suffisent pour des Shorts 720p (lent).
- Docker + Docker Compose installés. Un nom de domaine pointant vers le serveur (enregistrement A).
- Stockage : compter ~50–100 Mo par minute de vidéo 1080p (à surveiller, supprimez les vieux projets depuis l'app).
- Durée de rendu : dépend du CPU ; ordre de grandeur de quelques minutes pour une vidéo d'1 min en 1080p (**non mesuré**).
- Le 4K est possible mais très lourd en calcul et en disque.

## 2. Démarrage
```bash
git clone <votre dépôt> && cd avs
cp .env.example .env     # remplissez-le (voir README), COOKIE_SECURE=true, DOMAIN=studio.votredomaine.com
# PUBLIC_BASE_URL / FRONTEND_ORIGIN = https://studio.votredomaine.com
# GOOGLE_OAUTH_REDIRECT_URI = https://studio.votredomaine.com/api/youtube/callback
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```
Caddy obtient le certificat HTTPS automatiquement. Ouvrez `https://studio.votredomaine.com`.
Pare-feu : n'ouvrez que 80 et 443. **Sauvegardes** : volumes `pgdata` (base) et `media` ; conservez `APP_ENCRYPTION_KEY` (sans elle, clés et jetons chiffrés sont perdus).

Musique de fond (optionnel) : déposez des fichiers **dont vous avez les droits** dans `/data/media/music/` :
`docker compose cp ma-musique.mp3 api:/data/media/music/`

## 3. Clés API et comptes

| Service | Usage | Où l'obtenir | Payant ? |
|---|---|---|---|
| Google Gemini | scripts, idées, SEO **et voix** (option gratuite) | aistudio.google.com/apikey | Palier gratuit limité (quotas ; contenu possiblement utilisé par Google). Modèles réglables via GEMINI_MODEL / GEMINI_TTS_MODEL. Intégration non testée contre l'API réelle. |
| Anthropic | scripts, idées, SEO (prioritaire si une clé est présente) | console.anthropic.com → API keys | Oui (au token) |
| Google Cloud Text-to-Speech | voix off | console.cloud.google.com → activer « Cloud Text-to-Speech API » → Identifiants → clé API (restreinte à cette API). Facturation à activer | Oui (au caractère, quota gratuit mensuel selon l'offre en vigueur) |
| Pexels | clips et photos libres | pexels.com/api | Gratuit (limites de requêtes) |
| OpenAI (optionnel) | voix de secours | platform.openai.com | Oui |
| YouTube Data API (clé, optionnel) | signaux de tendances réels | même projet Google Cloud | Quota gratuit |
| OAuth Google | publier sur votre chaîne | voir ci-dessous | Gratuit |

### Connecter YouTube (OAuth 2.0)
1. Google Cloud Console → projet → **activer « YouTube Data API v3 »**.
2. **Écran de consentement OAuth** : type Externe, ajoutez votre compte en utilisateur test, ajoutez les scopes `youtube.upload` et `youtube.readonly`.
   ⚠️ En mode **« Testing »**, les jetons de rafraîchissement **expirent après 7 jours** : passez l'application en **« In production »** (écran « application non validée » affiché, acceptable pour un usage personnel).
3. Identifiants → **ID client OAuth → Application Web** ; URI de redirection autorisée = `GOOGLE_OAUTH_REDIRECT_URI`. Copiez client ID / secret dans `.env`.
4. Dans l'app : **Chaînes YouTube → Connecter**, choisissez la chaîne sur l'écran Google.

Limites YouTube à connaître :
- **Audit obligatoire** : tant que le projet Google Cloud n'a pas passé l'audit « YouTube API Services », les vidéos téléversées par l'API sont **verrouillées en privé**. Demandez l'audit via le formulaire YouTube API Services.
- **Quota** : 10 000 unités/jour par défaut ; un upload coûte ~1 600 unités → **~6 vidéos/jour** maximum sans demande d'extension.
- Miniature personnalisée : la chaîne doit être **vérifiée par téléphone**.
- Les Shorts sont des vidéos verticales/carrées **≤ 3 minutes** ; l'API n'a pas d'option « Short ».
- Si votre contenu est réaliste et synthétique, YouTube peut exiger une déclaration : option **Réglages → Déclarer contenu synthétique**.
- Respectez les conditions d'utilisation de YouTube (contenu répétitif/de faible valeur, etc.) et les licences des médias/musiques.

## 4. Tableau des coûts estimés (**estimations**, vérifiez les tarifs actuels)

Hypothèses configurables dans `backend/app/config.py` (`price_*`) : LLM 3 $/15 $ par million de tokens (entrée/sortie), TTS Chirp3-HD 30 $/million de caractères.

| Poste | Short 30–60 s | Vidéo 5 min | Vidéo 10 min |
|---|---|---|---|
| Scripts + SEO (Anthropic) | ~0,06 $ | ~0,15 $ | ~0,25 $ |
| Voix (Google TTS) | ~0,03 $ | ~0,13 $ | ~0,26 $ |
| Médias (Pexels) | 0 $ | 0 $ | 0 $ |
| Rendu FFmpeg | 0 $ (votre serveur) | 0 $ | 0 $ |
| **Total variable** | **~0,09 $** | **~0,3 $** | **~0,5 $** |
| Serveur VPS | ~15–30 €/mois (selon fournisseur) |
| Domaine | ~10–15 €/an |

Les budgets (Réglages) arrêtent automatiquement la production quand ils sont atteints. Les coûts affichés sont des estimations, pas la facture réelle.
