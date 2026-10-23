#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Inventaire - serveur web minimaliste (bibliothèque standard Python uniquement).

    python inventaire.py                 écoute sur 127.0.0.1 + l'IP Tailscale
    python inventaire.py --port 9000     autre port
    python inventaire.py --host 0.0.0.0  toutes les interfaces (réseau local compris)

Les données sont enregistrées dans inventaire.json et les images dans images/,
à côté de ce fichier (modifiable avec --data).
"""
import argparse
import base64
import html
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_FILE = os.path.join(BASE_DIR, "index.html")
STATIC_DIR = os.path.join(BASE_DIR, "static")
STATIC = {  # fichiers servis tels quels : nom -> type
    "icon.svg": "image/svg+xml", "icon-192.png": "image/png", "icon-512.png": "image/png",
    "apple-touch-icon.png": "image/png", "icon.ico": "image/x-icon",
    "manifest.webmanifest": "application/manifest+json",
}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
MAX_BODY = 12 * 1024 * 1024
MAX_IMAGE = 6 * 1024 * 1024
MAX_PAGE = 3 * 1024 * 1024
IMG_NAME = re.compile(r"^[0-9a-f]{32}\.(?:jpg|png|gif|webp|avif)$")
MIME = {"jpg": "image/jpeg", "png": "image/png", "gif": "image/gif",
        "webp": "image/webp", "avif": "image/avif"}


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def clean(text, limit=120):
    return " ".join(str(text or "").split())[:limit]


def fold(text):
    return clean(text).casefold()


def to_qty(value):
    try:
        return max(0, min(10 ** 9, int(float(value))))
    except (TypeError, ValueError, OverflowError):
        raise ApiError(400, "Quantité invalide")


# --------------------------------------------------------------------------- #
#  Images : téléchargement et recherche sur internet
# --------------------------------------------------------------------------- #

def sniff(data):
    """Type d'image d'après les premiers octets (SVG refusé volontairement)."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[4:12] in (b"ftypavif", b"ftypavis"):
        return "avif"
    return None


def fetch(url, limit, timeout=8, headers=None):
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError("URL non supportée")
    # Importé à la demande : le serveur au repos n'a pas besoin de ssl/urllib.
    import urllib.request
    hdrs = {"User-Agent": UA, "Accept": "*/*",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read(limit + 1)
    if len(data) > limit:
        raise ValueError("fichier trop volumineux")
    return data


def _bing(query, n):
    page = fetch("https://www.bing.com/images/search?form=HDRSC2&first=1&q="
                 + quote_plus(query), MAX_PAGE,
                 headers={"Cookie": "SRCHHPGUSR=ADLT=MODERATE"}).decode("utf-8", "replace")
    out = []
    for m in re.finditer(r'\bm="(\{[^"]*\})"', page):
        try:
            info = json.loads(html.unescape(m.group(1)))
        except ValueError:
            continue
        urls = [u for u in (info.get("turl"), info.get("murl")) if u]
        if urls:
            out.append({"thumb": urls[0], "urls": urls})
    if not out:  # mise en page différente : on cherche directement les liens d'images
        for murl in re.findall(r'"murl":"(https?://[^"]+)"', html.unescape(page)):
            out.append({"thumb": murl, "urls": [murl]})
    return out[:n]


def _duckduckgo(query, n):
    page = fetch("https://duckduckgo.com/?iax=images&ia=images&q=" + quote_plus(query),
                 MAX_PAGE).decode("utf-8", "replace")
    m = re.search(r"vqd=[\"']?([\d-]+)", page)
    if not m:
        return []
    data = json.loads(fetch(
        "https://duckduckgo.com/i.js?l=fr-fr&o=json&f=,,,&p=1&q=%s&vqd=%s"
        % (quote_plus(query), m.group(1)),
        MAX_PAGE, headers={"Referer": "https://duckduckgo.com/"}))
    out = []
    for r in data.get("results", [])[:n]:
        urls = [u for u in (r.get("thumbnail"), r.get("image")) if u]
        if urls:
            out.append({"thumb": urls[0], "urls": urls})
    return out


def _openverse(query, n):
    data = json.loads(fetch("https://api.openverse.org/v1/images/?page_size=%d&q=%s"
                            % (n, quote_plus(query)), MAX_PAGE))
    out = []
    for r in data.get("results", []):
        urls = [u for u in (r.get("thumbnail"), r.get("url")) if u]
        if urls:
            out.append({"thumb": urls[0], "urls": urls})
    return out


def _commons(query, n):
    data = json.loads(fetch(
        "https://commons.wikimedia.org/w/api.php?action=query&format=json"
        "&generator=search&gsrnamespace=6&prop=imageinfo&iiprop=url&iiurlwidth=400"
        "&gsrlimit=%d&gsrsearch=%s" % (n, quote_plus(query)), MAX_PAGE))
    pages = sorted(data.get("query", {}).get("pages", {}).values(),
                   key=lambda p: p.get("index", 0))
    out = []
    for p in pages:
        info = (p.get("imageinfo") or [{}])[0]
        thumb = info.get("thumburl")
        if thumb and not thumb.lower().endswith(".svg"):
            out.append({"thumb": thumb, "urls": [thumb]})
    return out


def _google(query, n):
    # Version HTML simple de Google Images (sans JavaScript).
    page = fetch("https://www.google.com/search?tbm=isch&gbv=1&hl=fr&q=" + quote_plus(query),
                 MAX_PAGE, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                                    "Cookie": "CONSENT=YES+; SOCS=CAI"}).decode("utf-8", "replace")
    urls = re.findall(r'src="(https://encrypted-tbn\d\.gstatic\.com/images\?[^"]+)"', page)
    return [{"thumb": html.unescape(u), "urls": [html.unescape(u)]} for u in urls[:n]]


def _yahoo(query, n):
    page = fetch("https://images.search.yahoo.com/search/images?p=" + quote_plus(query),
                 MAX_PAGE).decode("utf-8", "replace")
    out = []
    for u in re.findall(r"""data-src=['"](https://[^'"]+)['"]""", page):
        u = html.unescape(u)
        if "mm.bing.net/th" in u or "yimg.com" in u:
            out.append({"thumb": u, "urls": [u]})
    return out[:n]


def _wikipedia(lang):
    def engine(query, n):
        data = json.loads(fetch(
            "https://%s.wikipedia.org/w/api.php?action=query&format=json&generator=search"
            "&prop=pageimages&piprop=thumbnail&pithumbsize=400&gsrlimit=%d&gsrsearch=%s"
            % (lang, n, quote_plus(query)), MAX_PAGE))
        pages = sorted(data.get("query", {}).get("pages", {}).values(),
                       key=lambda p: p.get("index", 0))
        return [{"thumb": p["thumbnail"]["source"], "urls": [p["thumbnail"]["source"]]}
                for p in pages if p.get("thumbnail", {}).get("source")]
    engine.__name__ = "_wikipedia_" + lang
    return engine


def _flickr(query, n):
    tags = ",".join(w for w in re.split(r"[^\w]+", query.lower()) if w)
    data = json.loads(fetch("https://www.flickr.com/services/feeds/photos_public.gne"
                            "?format=json&nojsoncallback=1&tagmode=all&tags=" + quote_plus(tags),
                            MAX_PAGE))
    out = []
    for it in data.get("items", [])[:n]:
        small = (it.get("media") or {}).get("m")
        if small:
            out.append({"thumb": small, "urls": [small.replace("_m.", "_z."), small]})
    return out


# Par ordre de préférence : les premiers résultats affichés viennent des premiers moteurs.
ENGINES = (_bing, _google, _duckduckgo, _yahoo, _openverse,
           _wikipedia("fr"), _wikipedia("en"), _commons, _flickr)
PER_ENGINE = 6
MAX_RESULTS = 30
_cache = {}
_cache_lock = threading.Lock()


def query_variants(query):
    """La requête, puis des versions simplifiées si rien n'est trouvé."""
    import unicodedata
    plain = unicodedata.normalize("NFKD", query).encode("ascii", "ignore").decode()
    plain = " ".join(re.sub(r"[^\w./+-]+", " ", plain).split())
    words = plain.split()
    out = []
    for q in (query, plain, " ".join(words[:2]), words[0] if words else ""):
        if q and q not in out:
            out.append(q)
    return out


def _search_all(query, n):
    """Lance tous les moteurs en parallèle ; n'attend pas les plus lents."""
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
    pool = ThreadPoolExecutor(len(ENGINES))
    futures = [pool.submit(engine, query, n) for engine in ENGINES]
    pool.shutdown(wait=False)
    # Jusqu'à 3 s pour tout le monde, puis on continue seulement s'il n'y a encore rien.
    done, pending = wait(futures, timeout=3)
    deadline = time.monotonic() + 6
    while pending and not any(f.exception() is None and f.result() for f in done):
        left = deadline - time.monotonic()
        if left <= 0:
            break
        more, pending = wait(pending, timeout=left, return_when=FIRST_COMPLETED)
        done |= more
    results, seen = [], set()
    for f in futures:  # ordre des moteurs conservé
        if f not in done or f.exception() is not None:
            continue
        for r in f.result()[:PER_ENGINE]:
            if r["thumb"] not in seen:
                seen.add(r["thumb"])
                results.append(r)
    return results[:MAX_RESULTS]


def search_images(query, n=PER_ENGINE):
    """Interroge tous les moteurs en parallèle et fusionne les résultats."""
    query = clean(query, 200)
    if not query:
        return []
    with _cache_lock:
        if query in _cache:
            return _cache[query]
    results = []
    for q in query_variants(query):
        results = _search_all(q, n)
        if results:
            break
    if results:
        with _cache_lock:
            if len(_cache) >= 40:
                _cache.pop(next(iter(_cache)))
            _cache[query] = results
    return results


# --------------------------------------------------------------------------- #
#  Stockage JSON
# --------------------------------------------------------------------------- #

def wants_image(payload):
    return bool(payload.get("image_data") or payload.get("image_urls") or payload.get("auto_image"))


class Store:
    def __init__(self, path):
        self.path = path
        self.img_dir = os.path.join(os.path.dirname(path), "images")
        os.makedirs(self.img_dir, exist_ok=True)
        self.lock = threading.Lock()
        self.data = {"locations": [], "items": []}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                loaded = json.load(f)
            self.data["locations"] = list(loaded.get("locations", []))
            self.data["items"] = list(loaded.get("items", []))
        for item in self.data["items"]:
            # Ancien format (un seul lieu) -> liste de lieux avec une quantité chacun.
            if "stock" not in item:
                item["stock"] = [{"location": item.pop("location", "") or "",
                                  "qty": item.pop("qty", 0) or 0}]

    # -- utilitaires (appelés avec self.lock tenu) --

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def _find(self, item_id):
        for item in self.data["items"]:
            if item["id"] == item_id:
                return item
        raise ApiError(404, "Objet introuvable")

    def _check_unique(self, name, exclude=None):
        k = fold(name)
        for item in self.data["items"]:
            if item["id"] != exclude and fold(item["name"]) == k:
                raise ApiError(409, "Un objet nommé « %s » existe déjà" % item["name"])

    def _location(self, value, create=True):
        name = clean(value, 60)
        if not name:
            return ""
        for loc in self.data["locations"]:
            if fold(loc) == fold(name):
                return loc
        if not create:
            raise ApiError(404, "Lieu introuvable")
        self.data["locations"].append(name)
        return name

    def _stock(self, rows):
        """Valide la liste [{location, qty}] : lieux connus, un seul exemplaire par lieu."""
        if not isinstance(rows, list):
            raise ApiError(400, "Liste des lieux invalide")
        merged = {}
        for row in rows[:100]:
            if not isinstance(row, dict):
                raise ApiError(400, "Liste des lieux invalide")
            qty = to_qty(row.get("qty", 0))
            loc = self._location(row.get("location"))
            merged[loc] = merged.get(loc, 0) + qty
        return [{"location": l, "qty": q} for l, q in merged.items()] or [{"location": "", "qty": 0}]

    def _drop_file(self, name):
        if not name or not IMG_NAME.match(name):
            return
        if any(i.get("image") == name for i in self.data["items"]):
            return
        try:
            os.remove(os.path.join(self.img_dir, name))
        except OSError:
            pass

    # -- images (hors verrou : le téléchargement peut être lent) --

    def store_image(self, payload):
        """Enregistre l'image demandée. Retourne (fichier | None, avertissement | None)."""
        data = None
        if payload.get("image_data"):
            raw = str(payload["image_data"])
            if raw.startswith("data:"):
                raw = raw.split(",", 1)[-1]
            try:
                data = base64.b64decode(raw)
            except ValueError:
                raise ApiError(400, "Image invalide")
            if len(data) > MAX_IMAGE:
                raise ApiError(413, "Image trop volumineuse")
            if not sniff(data):
                raise ApiError(400, "Format d'image non supporté")
        else:
            urls = list(payload.get("image_urls") or [])[:8]
            if payload.get("auto_image") and payload.get("name"):
                # Aucune image choisie : on prend les premiers résultats de recherche.
                for r in search_images(payload["name"])[:4]:
                    urls.extend(r["urls"])
            for url in urls:
                try:
                    candidate = fetch(str(url), MAX_IMAGE)
                except Exception:
                    continue
                if sniff(candidate):
                    data = candidate
                    break
            if data is None:
                return None, "L'image n'a pas pu être téléchargée."
        name = "%s.%s" % (uuid.uuid4().hex, sniff(data))
        with open(os.path.join(self.img_dir, name), "wb") as f:
            f.write(data)
        return name, None

    # -- API --

    def dump(self, **extra):
        with self.lock:
            return json.dumps(dict(self.data, **extra), ensure_ascii=False).encode("utf-8")

    def add_item(self, p):
        name = clean(p.get("name"))
        if not name:
            raise ApiError(400, "Le nom est obligatoire")
        if "stock" not in p:
            p["stock"] = [{"location": p.get("location"), "qty": p.get("qty", 1)}]
        with self.lock:
            self._check_unique(name)
        image, warn = self.store_image(p) if wants_image(p) else (None, None)
        with self.lock:
            try:
                self._check_unique(name)
                stock = self._stock(p["stock"])
            except ApiError:
                self._drop_file(image)
                raise
            now = int(time.time())
            self.data["items"].append({
                "id": uuid.uuid4().hex[:12], "name": name, "image": image,
                "stock": stock, "created": now, "updated": now,
            })
            self._save()
        return warn

    def update_item(self, item_id, p):
        name = clean(p.get("name")) if "name" in p else None
        if name is not None and not name:
            raise ApiError(400, "Le nom est obligatoire")
        with self.lock:
            self._find(item_id)
            if name is not None:
                self._check_unique(name, item_id)
        image, warn = self.store_image(p) if wants_image(p) else (None, None)
        with self.lock:
            try:
                item = self._find(item_id)
                if name is not None:
                    self._check_unique(name, item_id)
                stock = self._stock(p["stock"]) if "stock" in p else item["stock"]
            except ApiError:
                self._drop_file(image)
                raise
            old = None
            item["stock"] = stock
            if name is not None:
                item["name"] = name
            if image:
                old, item["image"] = item.get("image"), image
            elif p.get("remove_image"):
                old, item["image"] = item.get("image"), None
            item["updated"] = int(time.time())
            self._save()
            self._drop_file(old)
        return warn

    def delete_item(self, item_id):
        with self.lock:
            item = self._find(item_id)
            self.data["items"].remove(item)
            self._save()
            self._drop_file(item.get("image"))

    def add_location(self, value):
        if not clean(value, 60):
            raise ApiError(400, "Le nom du lieu est obligatoire")
        with self.lock:
            name = self._location(value)
            self._save()
        return name

    def rename_location(self, old, new):
        new = clean(new, 60)
        if not new:
            raise ApiError(400, "Le nom du lieu est obligatoire")
        with self.lock:
            old = self._location(old, create=False)
            for loc in self.data["locations"]:
                if loc != old and fold(loc) == fold(new):
                    raise ApiError(409, "Le lieu « %s » existe déjà" % loc)
            locs = self.data["locations"]
            locs[locs.index(old)] = new
            for item in self.data["items"]:
                for row in item["stock"]:
                    if row["location"] == old:
                        row["location"] = new
            self._save()
        return new

    def delete_location(self, value):
        with self.lock:
            name = self._location(value, create=False)
            self.data["locations"].remove(name)
            for item in self.data["items"]:
                # Les quantités de ce lieu passent « sans lieu ».
                rows = [dict(r, location="" if r["location"] == name else r["location"])
                        for r in item["stock"]]
                item["stock"] = self._stock(rows)
            self._save()


# --------------------------------------------------------------------------- #
#  Serveur HTTP
# --------------------------------------------------------------------------- #

class Handler(BaseHTTPRequestHandler):
    server_version = "Inventaire"
    store = None  # défini au démarrage

    def log_message(self, *args):
        pass

    def _send(self, status, body=b"", ctype="application/json; charset=utf-8", headers=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, status=200):
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _body(self):
        # Exiger du JSON force un « preflight » CORS : un autre site ne peut pas
        # modifier l'inventaire depuis le navigateur.
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            raise ApiError(415, "JSON attendu")
        origin = self.headers.get("Origin")
        hosts = (self.headers.get("Host"), self.headers.get("X-Forwarded-Host"))
        if origin and urlparse(origin).netloc not in hosts:
            raise ApiError(403, "Origine refusée")
        size = int(self.headers.get("Content-Length") or 0)
        if size > MAX_BODY:
            raise ApiError(413, "Requête trop volumineuse")
        try:
            obj = json.loads(self.rfile.read(size) or b"{}")
        except ValueError:
            raise ApiError(400, "JSON invalide")
        if not isinstance(obj, dict):
            raise ApiError(400, "JSON invalide")
        return obj

    def _route(self):
        url = urlparse(self.path)
        parts = [unquote(p) for p in url.path.strip("/").split("/")]
        return url, parts

    def _run(self, fn):
        try:
            fn()
        except ApiError as e:
            self._json({"error": e.message}, e.status)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as e:
            try:
                self._json({"error": "Erreur interne : %s" % e}, 500)
            except OSError:
                pass

    def _ok(self, warning=None, **extra):
        self._send(200, self.store.dump(warning=warning, **extra))

    # ---- GET ----

    def do_GET(self):
        self._run(self._get)

    do_HEAD = do_GET

    def _get(self):
        url, parts = self._route()
        if url.path in ("/", "/index.html"):
            with open(INDEX_FILE, "rb") as f:
                body = f.read()
            self._send(200, body, "text/html; charset=utf-8", {"Cache-Control": "no-cache"})
        elif url.path == "/api/data":
            self._send(200, self.store.dump(), headers={"Cache-Control": "no-store"})
        elif url.path == "/api/images":
            q = parse_qs(url.query).get("q", [""])[0]
            self._json({"results": search_images(q)})
        elif len(parts) == 2 and parts[0] == "img":
            self._image(parts[1])
        elif len(parts) == 1 and (parts[0] in STATIC or parts[0] == "favicon.ico"):
            name = "icon.ico" if parts[0] == "favicon.ico" else parts[0]
            with open(os.path.join(STATIC_DIR, name), "rb") as f:
                body = f.read()
            self._send(200, body, STATIC[name], {"Cache-Control": "public, max-age=86400"})
        else:
            raise ApiError(404, "Introuvable")

    def _image(self, name):
        if not IMG_NAME.match(name):
            raise ApiError(404, "Introuvable")
        try:
            f = open(os.path.join(self.store.img_dir, name), "rb")
        except OSError:
            raise ApiError(404, "Introuvable")
        with f:
            self.send_response(200)
            self.send_header("Content-Type", MIME[name.rsplit(".", 1)[1]])
            self.send_header("Content-Length", str(os.fstat(f.fileno()).st_size))
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
            self.end_headers()
            if self.command != "HEAD":
                shutil.copyfileobj(f, self.wfile, 64 * 1024)

    # ---- écriture ----

    def do_POST(self):
        self._run(self._post)

    def do_PUT(self):
        self._run(self._put)

    def do_DELETE(self):
        self._run(self._delete)

    def _post(self):
        _, parts = self._route()
        body = self._body()
        if parts == ["api", "items"]:
            self._ok(self.store.add_item(body))
        elif parts == ["api", "locations"]:
            self._ok(name=self.store.add_location(body.get("name")))
        else:
            raise ApiError(404, "Introuvable")

    def _put(self):
        _, parts = self._route()
        body = self._body()
        if len(parts) == 3 and parts[:2] == ["api", "items"]:
            self._ok(self.store.update_item(parts[2], body))
        elif len(parts) == 3 and parts[:2] == ["api", "locations"]:
            self._ok(name=self.store.rename_location(parts[2], body.get("name")))
        else:
            raise ApiError(404, "Introuvable")

    def _delete(self):
        _, parts = self._route()
        self._body()
        if len(parts) == 3 and parts[:2] == ["api", "items"]:
            self.store.delete_item(parts[2])
        elif len(parts) == 3 and parts[:2] == ["api", "locations"]:
            self.store.delete_location(parts[2])
        else:
            raise ApiError(404, "Introuvable")
        self._ok()


# --------------------------------------------------------------------------- #
#  Tailscale et démarrage
# --------------------------------------------------------------------------- #

def is_tailscale_ip(ip):
    try:
        a, b, _, _ = (int(x) for x in ip.split("."))
    except ValueError:
        return False
    return a == 100 and 64 <= b <= 127  # plage CGNAT 100.64.0.0/10


TAILSCALE_CLI = ("tailscale", r"C:\Program Files\Tailscale\tailscale.exe",
                 "/Applications/Tailscale.app/Contents/MacOS/Tailscale")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def tailscale_info():
    """Retourne (ip, nom_magicdns, commande) de cette machine sur Tailscale."""
    for cli in TAILSCALE_CLI:
        try:
            out = subprocess.run([cli, "status", "--json"], capture_output=True, timeout=5,
                                 creationflags=NO_WINDOW)
            me = json.loads(out.stdout or b"{}").get("Self") or {}
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
        ips = [ip for ip in me.get("TailscaleIPs") or [] if is_tailscale_ip(ip)]
        if ips:
            return ips[0], (me.get("DNSName") or "").rstrip(".") or None, cli
    # Sans la commande tailscale : on cherche une adresse 100.64.0.0/10 sur la machine.
    candidates = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("100.100.100.100", 53))
            candidates.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        candidates += socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        pass
    for ip in candidates:
        if is_tailscale_ip(ip):
            return ip, None, None
    return None, None, None


def tailscale_https(cli, port, https_port):
    """Active « tailscale serve » : https://<machine>.ts.net:<https_port> -> ce serveur.

    Retourne (True, None) si c'est actif, sinon (False, explication)."""
    try:
        out = subprocess.run([cli, "serve", "--bg", "--https=%d" % https_port,
                              "http://127.0.0.1:%d" % port],
                             capture_output=True, timeout=20, creationflags=NO_WINDOW)
        text = (out.stdout + out.stderr).decode("utf-8", "replace")
        if out.returncode == 0:
            return True, None
    except subprocess.TimeoutExpired as e:
        # Tailscale attend que HTTPS soit autorisé sur le tailnet.
        text = ((e.stdout or b"") + (e.stderr or b"")).decode("utf-8", "replace")
    except OSError as e:
        return False, str(e)
    link = re.search(r"https://login\.tailscale\.com/\S+", text)
    if link:
        return False, ("HTTPS n'est pas encore autorisé sur votre réseau Tailscale.\n"
                       "               Ouvrez ce lien, acceptez, puis relancez :\n"
                       "               " + link.group(0))
    if "denied" in text.lower() or "operator" in text.lower():
        return False, ("Tailscale refuse l'accès. Sous Linux, lancez une fois :\n"
                       "               sudo tailscale set --operator=$USER")
    first = text.strip().splitlines()[0] if text.strip() else "erreur inconnue"
    return False, first + "\n               (mettez Tailscale à jour si la version est ancienne)"


def tailscale_https_off(cli, https_port):
    try:
        subprocess.run([cli, "serve", "--https=%d" % https_port, "off"], capture_output=True, timeout=10,
                       creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        pass


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_lan = False

    def verify_request(self, request, client_address):
        # Seuls ce PC et les appareils Tailscale peuvent se connecter (sauf --lan).
        ip = client_address[0]
        return self.allow_lan or ip.startswith("127.") or ip == "::1" or is_tailscale_ip(ip)


def main():
    ap = argparse.ArgumentParser(description="Serveur d'inventaire")
    ap.add_argument("--port", type=int, default=8080, help="port (8080 par défaut)")
    ap.add_argument("--lan", action="store_true",
                    help="autoriser aussi les appareils du réseau local (Wi-Fi)")
    ap.add_argument("--https-port", type=int,
                    help="port de l'adresse HTTPS Tailscale (par défaut le même que --port)")
    ap.add_argument("--no-https", action="store_true",
                    help="ne pas activer HTTPS via Tailscale (accès Tailscale en http)")
    ap.add_argument("--data", default=os.path.join(BASE_DIR, "inventaire.json"),
                    help="fichier JSON des données")
    args = ap.parse_args()

    Handler.store = Store(os.path.abspath(args.data))
    Server.allow_lan = args.lan
    lines = ["  Sur ce PC  : http://localhost:%d" % args.port]

    ts_ip, ts_name, cli = tailscale_info()
    https_on = False
    https_port = args.https_port or args.port
    if not ts_ip:
        lines.append("  Tailscale  : non détecté (connectez Tailscale puis relancez)")
    elif args.no_https:
        lines.append("  Tailscale  : http://%s:%d" % (ts_name or ts_ip, args.port))
    else:
        if not cli:
            why = "commande tailscale introuvable"
        elif not ts_name:
            why = "activez MagicDNS dans la console Tailscale"
        else:
            print("\n  Activation de HTTPS sur Tailscale...", flush=True)
            https_on, why = tailscale_https(cli, args.port, https_port)
        if https_on:
            lines.append("  Tailscale  : https://%s%s"
                         % (ts_name, "" if https_port == 443 else ":%d" % https_port))
        else:
            lines.append("  Tailscale  : http://%s:%d   (sans HTTPS)" % (ts_name or ts_ip, args.port))
            lines.append("  HTTPS      : " + why)

    # Avec HTTPS, Tailscale passe par localhost : inutile d'ouvrir le port au réseau
    # (et pas de demande du pare-feu Windows).
    direct_ts = ts_ip and not https_on
    host = "0.0.0.0" if args.lan or direct_ts else "127.0.0.1"
    try:
        server = Server((host, args.port), Handler)
    except OSError as e:
        print("Impossible de démarrer sur le port %d (%s)." % (args.port, e))
        print("Le serveur tourne peut-être déjà, ou essayez : python inventaire.py --port 8081")
        sys.exit(1)

    print()
    print("  Inventaire lancé")
    print()
    print("\n".join(lines))
    if args.lan:
        print("  Réseau local autorisé")
    print()
    print("  Données    : %s" % Handler.store.path)
    print("  Laissez cette fenêtre ouverte. Ctrl+C pour arrêter.")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Arrêt.")
    finally:
        if https_on:
            tailscale_https_off(cli, https_port)


if __name__ == "__main__":
    main()
