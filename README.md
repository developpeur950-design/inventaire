# Inventaire

Petit serveur d'inventaire (composants électroniques ou n'importe quoi d'autre) en mode
sombre, accessible depuis le PC et depuis tous vos appareils Tailscale.

- **Python 3.8+ uniquement**, aucune dépendance à installer (bibliothèque standard, ~20 Mo de RAM).
- Données enregistrées dans `inventaire.json`, images téléchargées dans `images/` (à côté du script).

## Lancer

```bash
python inventaire.py
```

La console affiche les adresses :

```
Inventaire démarré  (Ctrl+C pour arrêter)
  Adresse    http://localhost:8080
  Tailscale  http://100.x.y.z:8080
  MagicDNS   http://mon-pc.tailnet-xxxx.ts.net:8080
```

Options :

| Option | Effet |
|---|---|
| `--port 9000` | change le port (8080 par défaut) |
| `--host 0.0.0.0` | écoute sur toutes les interfaces (réseau local compris) |
| `--data D:\stock\inventaire.json` | autre emplacement pour les données (les images vont à côté) |

Par défaut le serveur écoute **uniquement** sur `127.0.0.1` et sur l'IP Tailscale : il n'est
pas visible sur le réseau local (Wi-Fi). Tailscale doit être connecté **avant** le lancement.
Sous Windows, autorisez Python dans le pare-feu à la première exécution.

## Utilisation

- Bouton **+** (ou touche `+`) : ajouter un objet. Le nom est unique (majuscules ignorées).
  Les images sont cherchées sur internet pendant la saisie du nom et la première est
  sélectionnée automatiquement. On peut en choisir une autre, changer la recherche, coller
  l'URL d'une image ou importer une photo depuis l'appareil.
- **− / +** sur une fiche : changer la quantité (maintenir appuyé pour aller vite), ou taper
  le nombre directement.
- Liste **lieu** : choisir un lieu, ou **+ Ajouter un lieu…** en bas de la liste.
- **⋮** en haut à droite d'une fiche (ou clic sur l'image) : modifier / supprimer.
- Barre de recherche (touche `/`) : cherche dans les noms et les lieux, sans tenir compte des accents.
- Tri par nom, quantité, lieu, date d'ajout ou de modification, et filtre par lieu.
- Bouton **Lieux** : renommer ou supprimer des lieux.
