# Inventaire

Inventaire simple (composants électroniques ou n'importe quoi d'autre), accessible depuis
le PC et depuis vos appareils Tailscale. Rien à installer à part Python 3.8 ou plus récent.

## Télécharger

```bash
git clone -b claude/serene-ritchie-50q41l https://github.com/developpeur950-design/inventaire.git
cd inventaire
```

## Lancer

- **Windows** : double-clic sur `lancer.bat` (ou `py inventaire.py`).
  `creer-raccourci.bat` ajoute un raccourci « Inventaire » avec son icône sur le Bureau.
- **Linux / macOS** : `./lancer.sh` (ou `python3 inventaire.py`).

La fenêtre affiche les adresses à ouvrir :

```
  Inventaire lancé

  Sur ce PC  : http://localhost:8080
  Tailscale  : https://mon-pc.tailnet-xxxx.ts.net:8080
```

## HTTPS sur Tailscale

Au lancement, le programme active `tailscale serve`, qui fournit l'adresse
`https://<machine>.<tailnet>.ts.net:<port>` avec un vrai certificat (pas d'alerte du navigateur).
Le port est le même que `--port` (8080 par défaut), ou celui de `--https-port`.
Il le désactive à l'arrêt (Ctrl+C).

La première fois, HTTPS doit être autorisé sur votre réseau Tailscale : si c'est le cas,
la fenêtre affiche un lien, il suffit de l'ouvrir, d'accepter, puis de relancer.
MagicDNS doit être activé (c'est le cas par défaut). Sous Linux, si Tailscale refuse
l'accès, lancez une fois `sudo tailscale set --operator=$USER`.

Tant que HTTPS n'est pas disponible, l'accès Tailscale se fait en `http://` (adresse affichée).

## Icône / application

Sur téléphone ou sur PC, ouvrez l'adresse HTTPS puis « Ajouter à l'écran d'accueil »
(ou « Installer l'application ») : l'inventaire s'ouvre alors comme une application, avec son icône.

## Options

`--port 8081` (autre port), `--https-port 8443` (autre port pour l'adresse HTTPS Tailscale), `--lan` (autoriser aussi le Wi-Fi local), `--no-https`
(ne pas activer HTTPS), `--data chemin\inventaire.json` (autre emplacement des données).

## Données

- `inventaire.json` : la liste des objets et des lieux. Un objet peut être rangé dans
  plusieurs lieux, avec une quantité pour chacun (les anciens fichiers sont convertis automatiquement).
- `images/` : les images, téléchargées sur le PC.

Pour sauvegarder, copiez ces deux éléments.
