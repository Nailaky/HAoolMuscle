# Cool Muscle Studio

Configuration, programmation et diagnostic des servomoteurs **Cool Muscle CM1**
(Myostat / Muscle Corporation) depuis **Home Assistant**, à travers un pont
série ESP32-S3 sous ESPHome. L'objectif est de couvrir ce que fait le logiciel
Windows *Control Room*, en mieux, avec une interface entièrement en français.

> État du projet : **étape 1 (pont série et terminal)** terminée, validée sur
> simulateur et compilée pour l'ESP32, pas encore essayée sur un moteur réel.
> Voir [docs/architecture.md](docs/architecture.md) pour le plan et
> [docs/questions-ouvertes.md](docs/questions-ouvertes.md) pour les décisions
> en attente.

## Contenu du dépôt

| Dossier | Rôle |
|---|---|
| `cool_muscle_studio/` | L'app Home Assistant (ex add-on) avec ingress : backend Python `cmstudio`, tests, configuration d'app. |
| `esphome/` | `cool-muscle.yaml` (configuration de l'ESP32) et, à l'étape 1, le composant externe `cm1_bridge`. |
| `reference/cml_reference.yaml` | Base de données du protocole CML : commandes, requêtes, registres, paramètres K, états, avec sources et statut (documenté / à confirmer / conflit). |
| `docs/` | Architecture, protocole TCP du pont, questions ouvertes. |

## Installation

Prérequis : Home Assistant OS ou Supervised (les apps ont besoin du
Supervisor), ESPHome 2026.3 ou plus récent.

1. Flasher `esphome/cool-muscle.yaml` depuis le tableau de bord ESPHome en
   gardant votre clé API et vos secrets Wi-Fi. Le composant `cm1_bridge` est
   importé automatiquement depuis ce dépôt (`external_components`). Toutes
   les entités existantes sont conservées ; trois s'ajoutent : « Mode
   maintenance », « Application connectée », « Clients connectés ».
2. *Paramètres → Apps → Installer une app → ⋮ → Dépôts*, ajouter l'URL de ce
   dépôt, puis installer **Cool Muscle Studio**.
3. Dans les options de l'app, indiquer l'adresse du pont (`cool-muscle.local`,
   port 6638), démarrer l'app et ouvrir « Cool Muscle » dans la barre latérale.

Mode d'emploi détaillé (terminal, mode maintenance, dépannage) :
[cool_muscle_studio/DOCS.md](cool_muscle_studio/DOCS.md). Protocole entre
l'app et le pont : [docs/protocole-tcp.md](docs/protocole-tcp.md).

## Développement

Prérequis : Python 3.12 ou plus récent.

```bash
pip install -e cool_muscle_studio/backend[dev]
```

Lancer les tests :

```bash
pytest cool_muscle_studio/backend -q
```

Lancer le simulateur de moteur (face « pont », protocole du composant
`cm1_bridge`, port 6638) :

```bash
python -m cmstudio.sim --mode bridge --port 6638 -v
```

Face « moteur nu » (comportement du port série du moteur, commandes terminées
par CR, réponses CR LF) :

```bash
python -m cmstudio.sim --mode raw --port 6639 -v
```

Puis, par exemple avec `nc 127.0.0.1 6638`, taper `TX ?85.1` (pont) ou
`?85.1` (moteur nu). Les formats de réponse qui ne sont pas documentés par
Myostat sont des hypothèses, listées dans
`cool_muscle_studio/backend/cmstudio/sim/formats.py`, et seront remplacés par
les captures du vrai moteur.

Lancer l'app en local avec un simulateur de pont intégré, puis ouvrir
<http://127.0.0.1:8099/> :

```bash
python -m cmstudio.app --dev --port 8099
```

Valider et compiler la configuration ESPHome (Docker) : une copie de
développement avec le composant local et une clé API factice se crée ainsi :

```bash
cd esphome && mkdir -p .dev && printf 'wifi_ssid: "x"\nwifi_password: "xxxxxxxx"\n' > .dev/secrets.yaml && sed -e 's|source: github://Nailaky/HAoolMuscle@main|source: {type: local, path: ../components}|' -e '/^    path: esphome\/components$/d' -e '/^    refresh: 1h$/d' -e "s|key: \"REMPLACER_PAR_LA_CLE_GENEREE_PAR_ESPHOME\"|key: \"$(python -c 'import base64,os;print(base64.b64encode(os.urandom(32)).decode())')\"|" cool-muscle.yaml > .dev/cool-muscle.yaml && docker run --rm -v "$PWD:/config" ghcr.io/esphome/esphome:2026.10.0 compile .dev/cool-muscle.yaml
```

Bibliothèque `cmstudio` :

- `cmstudio.reference` : chargement de `reference/cml_reference.yaml` ;
- `cmstudio.cml` : analyseur CML (`parse_program`), prétraitement CMP
  (`cmp.compile_cmp`), validation (`validate.validate`) ;
- `cmstudio.status` : décodage des codes Ux ;
- `cmstudio.units` : table K37, conversions impulsions/degrés et S/tr/min ;
- `cmstudio.protocol` : messages du protocole TCP du pont ;
- `cmstudio.sim` : simulateur de chaîne de moteurs ;
- `cmstudio.app` : serveur web de l'app (client de pont, journal, API,
  WebSocket, frontend statique sans étape de build).

## Sécurité

Aucun essai n'est fait sur un moteur réel sans accord explicite. Toute
commande de mouvement ou de configuration passera par une confirmation dans
l'interface, et toutes les écritures seront journalisées.

## Sources

Documentation officielle Myostat : <https://docs.myostat.ca/cm1-c/user-guide>
(guide utilisateur v3.00 et RT3 Quick Reference Guide v3.14.00).
