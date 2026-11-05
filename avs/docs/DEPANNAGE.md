# Guide de dépannage

| Symptôme | Cause probable | Solution |
|---|---|---|
| L'API refuse de démarrer : « APP_SECRET_KEY… » / « APP_ENCRYPTION_KEY… » | Clés par défaut ou invalides | Générez-les (commandes dans le README) |
| Pas d'admin / connexion impossible | `ADMIN_PASSWORD` vide ou « change-me… » au premier démarrage | Corrigez `.env`, supprimez le volume `pgdata` (si base vide) et relancez |
| « Clé API Anthropic manquante » | Clé absente | Réglages → Clés API |
| « Aucun fournisseur vocal configuré » | Pas de clé Google TTS ni OpenAI | Ajoutez une clé ; vérifiez que l'API Text-to-Speech est activée et la facturation active |
| Google TTS 403/400 | Clé restreinte à une autre API, facturation inactive, voix indisponible pour la langue | Le système bascule seul sur une voix standard puis OpenAI ; corrigez la clé |
| Scènes avec « carte de remplacement » | Pas de clé Pexels ou aucun résultat | Ajoutez la clé Pexels, reformulez la « recherche visuelle » (anglais) puis Régénérer → Médias, ou remplacez le média à la main |
| Sous-titres arabes en carrés | Police absente | L'image Docker inclut `fonts-noto-core` ; reconstruisez l'image |
| Vidéo bloquée « En attente » | Worker arrêté ou Redis indisponible | `docker compose logs worker redis` ; `docker compose restart worker` |
| Échec « Budget … atteint » | Budget par vidéo/jour/mois dépassé | Réglages → Budgets, puis Régénérer |
| « Contrôle qualité échoué » | Voir la carte Contrôle qualité de la vidéo | Corrigez (SEO, son…) puis Régénérer à partir de l'étape concernée |
| Publication : « Jeton expiré ou révoqué » | Consentement en mode Testing (7 jours) ou accès révoqué | Passez l'écran de consentement « In production », reconnectez la chaîne |
| La vidéo YouTube est en privé malgré « public » | Projet non audité par YouTube | Demandez l'audit YouTube API Services |
| `quotaExceeded` | 10 000 unités/jour atteintes | Attendez minuit (heure du Pacifique) ou demandez une extension de quota |
| Miniature non envoyée | Chaîne non vérifiée | Vérifiez la chaîne par téléphone dans YouTube Studio |
| « Redirect URI mismatch » | URI différente de celle de la console Google | Doit être identique à `GOOGLE_OAUTH_REDIRECT_URI` |
| L'app ne s'installe pas sur le téléphone | Pas en HTTPS | Déployez avec le domaine + Caddy |
| Upload interrompu | Coupure réseau | Bouton Publier à nouveau : l'upload **reprend** là où il s'est arrêté |

Logs : `docker compose logs -f api worker scheduler`. Chaque vidéo a aussi son **journal** dans l'application (tentatives, erreurs détaillées).
