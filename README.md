# Inventaire

Inventaire simple (composants électroniques ou n'importe quoi d'autre), accessible depuis
le PC et depuis vos appareils Tailscale. Rien à installer à part Python 3.8 ou plus récent.

## Télécharger

```bash
git clone -b claude/serene-ritchie-50q41l https://github.com/developpeur950-design/inventaire.git
cd inventaire
```

## Lancer

- **Windows** : double-clic sur `lancer.bat`, ou `py inventaire.py`
- **Linux / macOS** : `./lancer.sh`, ou `python3 inventaire.py`

La fenêtre affiche les adresses à ouvrir :

```
  Inventaire lancé

  Sur ce PC  : http://localhost:8080
  Tailscale  : http://100.x.y.z:8080
               http://mon-pc.tailnet-xxxx.ts.net:8080
```

Seuls ce PC et les appareils de votre réseau Tailscale peuvent s'y connecter.
Sous Windows, acceptez la demande du pare-feu au premier lancement.

Options : `--port 8081` (autre port), `--lan` (autoriser aussi le Wi-Fi local),
`--data chemin\inventaire.json` (autre emplacement des données).

## Données

- `inventaire.json` : la liste des objets et des lieux.
- `images/` : les images, téléchargées sur le PC.

Pour sauvegarder, copiez ces deux éléments.
