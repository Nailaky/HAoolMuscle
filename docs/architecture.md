# Cool Muscle Studio — proposition d'architecture (v0, à valider)

Date : 2026-10-21. Rien n'est encore implémenté : ce document est la proposition
demandée avant tout code. La base de données du protocole est dans
[`reference/cml_reference.yaml`](../reference/cml_reference.yaml) et les points
à trancher dans [`docs/questions-ouvertes.md`](questions-ouvertes.md).

## 1. Recommandation en trois lignes

1. **Côté ESP32** : un composant ESPHome externe dédié, `cm1_bridge`, hébergé
   dans ce dépôt et importé par `external_components`. Il possède l'UART,
   découpe les lignes, sert un petit protocole TCP texte multi-clients, arbitre
   l'accès au bus entre la logique robot embarquée et l'application, et porte
   le mode maintenance. Aucun composant existant (natif ou externe) ne sait
   partager l'UART avec la logique robot : voir §3.
2. **Côté Home Assistant** : une **app** (nouveau nom des add-ons depuis
   HA 2026.2) avec **ingress**, en Python, installée depuis ce dépôt GitHub
   via *Paramètres → Apps → Installer une app → ⋮ → Dépôts*. Pas d'intégration
   personnalisée : les entités existent déjà via ESPHome, et une app est le
   seul format qui offre une vraie interface web, des connexions TCP
   persistantes et un stockage de fichiers dans `/share`. Voir §4.
3. **Méthode** : simulateur CM1 et tests d'abord, puis quatre livraisons
   (pont + terminal, fiche moteur + éditeur K, fichiers + sauvegardes,
   graphiques). Voir §9.

## 2. Point de départ

Le `cool-muscle.yaml` actuel fait tout dans une lambda de 10 ms : lecture
octet par octet de l'UART, analyse des lignes (`K…=`, `Px…=`, `Ux…=`, bannière
`FW`/`ID`), séquence de démarrage (vérification de K23/K37/K52, `|4` si K37
change, `(`, `|2`), machine d'états repos / mouvement / alarme, file de
commandes robot, réactivation automatique, champ « Commande CML » qui envoie
une ligne brute. Tout cela est conservé tel quel ; seul l'accès physique à
l'UART change de main (§3.4).

Contraintes retenues du cahier des charges : la logique robot reste sur
l'ESP32 et fonctionne sans Wi-Fi ; un seul fichier YAML flashable depuis le
tableau de bord ESPHome ; `?1000` et `?90` renvoient de nombreuses lignes ;
le mode maintenance doit être explicite, visible dans HA, et impossible
pendant un mouvement.

## 3. Canal série entre l'application et le moteur

### 3.1 Options évaluées (ESPHome 2026.10.0)

| Option | Ce que c'est | Pourquoi ça ne convient pas (ou pas seul) |
|---|---|---|
| `uart_tcp` (natif) | Copie brute UART ↔ une connexion TCP (serveur ou client). | Exige l'UART **en exclusivité** (« another component with the same uart_id is rejected… a lambda that uses the UART is not detected, so avoid them »). Un seul client. Jette les octets reçus quand personne n'est connecté : la logique robot ne verrait plus rien. |
| `serial_proxy` (natif, 2026.3) | Expose l'UART aux clients de l'API native (chiffrée). | Marqué **expérimental** (« may change at any time »), un seul abonné, exclusivité de l'UART, et l'intégration ESPHome de HA peut réclamer le port. À suivre, pas pour une base de production. |
| `uart_mux` (natif) | Bascule un UART entre un pont USB CDC-ACM et les composants locaux. | Conçu pour l'USB (ESP32-S3 en périphérique USB), une seule route à la fois, octets perdus pendant la bascule. Pas de TCP. |
| `stream_server` (externe, oxan) | Serveur TCP brut multi-clients, mûr, compatible esp-idf (vu avec ESPHome 2026.3 dans le code). | Son `loop()` lit l'UART en permanence (`read()` appelé même sans client) : il **vole les octets** à la lambda robot. Pas de trames, pas d'horodatage, pas d'arbitrage ni de mode maintenance. |
| Actions et événements de l'API native | `api: actions:` pour envoyer une ligne, `homeassistant.event` pour chaque ligne reçue. | Une ligne = un événement sur le bus HA (latence, regroupement 100 ms, charge), ordre non garanti côté app, pas de flux ; il faudrait en plus une intégration personnalisée pour les consommer. Acceptable pour exposer *l'état* du mode maintenance, pas pour un terminal. |
| **Composant dédié `cm1_bridge`** (externe, dans ce dépôt) | Possède l'UART, découpe en lignes, serveur TCP texte multi-clients, arbitre, mode maintenance, entités HA. | C'est la seule option qui résout le partage du bus. Coût : ~500 lignes de C++ et un `__init__.py` ESPHome, à maintenir ici. |

### 3.2 Conception de `cm1_bridge`

Le composant tourne dans la boucle principale ESPHome, sockets non bloquantes
(même mécanique que `stream_server`, dont la structure a été lue et sert de
référence pour la compatibilité esp-idf et les versions 2026.x).

Rôles :

- **Lecture UART** : assemble les lignes (CR, LF ou CR LF, K70=0 ou 1),
  120 caractères max, horodatage `millis()`.
- **Diffusion** : chaque ligne reçue va (a) à la lambda robot par un trigger
  `on_line`, (b) à tous les clients TCP.
- **Émission arbitrée** : une seule file de sortie vers le moteur, espacement
  minimal entre lignes (3 ms aujourd'hui dans la lambda, réglable), chaque
  ligne envoyée est aussi diffusée aux clients avec son origine (`LOCAL` ou
  `C<n>`), ce qui permet au terminal de distinguer l'écho d'une commande de
  l'ESP32 de celui d'une commande de l'utilisateur.
- **Deux modes** :
  - *Normal* : la logique robot est maîtresse. Les clients peuvent envoyer
    uniquement des commandes de lecture (liste blanche : `?…`, lecture d'un
    registre sans `=`, `_SKH` sans `=`) et l'arrêt d'urgence `*` (toujours
    accepté, par sécurité). Tout le reste est refusé avec un message
    d'erreur. C'est ce qui permet la fiche moteur et les graphiques en
    continu pendant que le robot travaille.
  - *Maintenance* : la logique robot est suspendue (entrées GPIO ignorées,
    aucun envoi propre), les clients ont la main sur tout.
- **Entrée en maintenance** : refusée si un mouvement est en cours, si la
  séquence de démarrage n'est pas terminée ou si le moteur est en alarme non
  acquittée (la lambda publie un drapeau `busy`). Demandée soit par le
  protocole TCP, soit par l'entité HA `switch` « Mode maintenance » (donc
  visible et pilotable partout dans HA, automatisations comprises).
- **Sortie de maintenance** : la lambda relance une resynchronisation :
  `?85`, `?90` (vérification de K23/K37/K52, réécriture si l'app les a
  changés, avec avertissement), `?99`, `?96` ; la position lue devient la
  position courante **sans mouvement** ; puis retour en mode normal. Détail
  à trancher dans les questions ouvertes (que faire si la position lue n'est
  ni 0° ni 180°).
- **Sécurité réseau** : option `allowed_ips` (le sous-réseau de HA), 4 clients
  max, lignes TX limitées à 60 caractères comme le champ actuel, déconnexion
  des clients muets (ping/pong).
- **Entités HA** : `switch` « Mode maintenance », `binary_sensor` « Client
  connecté », `sensor` « Clients connectés ». Les autres entités actuelles
  (Position, État, etc.) restent dans le YAML.

### 3.3 Protocole TCP (port 6638 par défaut, texte, une ligne = un message)

Client → ESP32 :

```
TX <ligne CML>          envoie la ligne au moteur (l'ESP32 ajoute le CR)
MAINT ON | MAINT OFF    demande d'entrée / sortie du mode maintenance
STATUS                  demande l'état (réponse EVT STATE)
PING                    réponse PONG
```

ESP32 → clients :

```
HELLO <version> <mode> <busy>          à la connexion
RX <ms> <ligne>                        ligne reçue du moteur
TX <ms> <origine> <ligne>              ligne envoyée au moteur (LOCAL ou C1..C4)
EVT <ms> STATE <mode> <busy>           changement de mode ou d'occupation
EVT <ms> MAINT REFUSED <raison>        entrée refusée (MOVING, STARTUP, ALARM)
ERR <ms> <code> <texte>                ligne refusée (FORBIDDEN, TOOLONG, QUEUE_FULL)
PONG
```

Lisible avec `nc`/`telnet`, donc facile à diagnostiquer. L'application ajoute
sa propre horloge murale à la réception ; les `<ms>` de l'ESP32 servent à
ordonner et à mesurer les délais de réponse.

### 3.4 Modifications de `cool-muscle.yaml` (toutes les fonctions conservées)

- `external_components: - source: github://<owner>/<repo>@main`
  `path: esphome/components`, `components: [cm1_bridge]`.
- Bloc `cm1_bridge:` avec `uart_id: motor_uart`, port, `allowed_ips`,
  et les trois entités.
- La section « 1. réception » de la lambda est remplacée par un trigger
  `on_line` qui empile les lignes dans un `globals` (`std::vector<std::string>`,
  comme `raw_queue` aujourd'hui) ; la lambda de 10 ms les dépile et appelle
  le même `parse_line`.
- `id(motor_uart).write_str(...)` devient `id(cm1).send_local(...)`.
- Un drapeau `maintenance` lu par la lambda : si vrai, elle n'exécute ni la
  file robot, ni ses interrogations, ni la reconfiguration, et vide la file
  `cmd_queue` à la sortie après resynchronisation.
- Le champ « Commande CML », les boutons, les capteurs et les réglages restent
  identiques (mêmes noms d'entités, pour ne pas casser les tableaux de bord).

Validation : `esphome config` puis `esphome compile` dans le conteneur
`ghcr.io/esphome/esphome:2026.10.0` (Docker est disponible sur ce poste ;
ESPHome n'y est pas installé en natif).

## 4. Format de l'application Home Assistant

### 4.1 Options

| Critère | App (ex add-on) avec ingress | Intégration personnalisée + panneau (HACS) | Les deux |
|---|---|---|---|
| Interface web riche (terminal, éditeur, graphiques) | Oui, n'importe quelle pile web, servie par l'app | Panneau `panel_custom` en Lit/JS chargé par le frontend HA ; backend limité aux websocket commands de HA | Oui |
| Connexions TCP persistantes vers 1..n ponts | Natif (processus dédié) | Possible en asyncio mais l'intégration vit dans le processus HA (contraintes de blocage, redémarrages de HA coupent les transferts) | Natif |
| Fichiers dans `/share` ou `/config` | `map: share` et `app_config` | `/config/…` seulement | Oui |
| Installation depuis un dépôt GitHub | Oui, dialogue « Dépôts » intégré (badge My Home Assistant possible) | Oui mais via HACS (à installer d'abord) | Deux dépôts/procédures |
| Prérequis | HA OS ou HA Supervised (Supervisor) | Toute installation | Supervisor |
| Entités HA (position, état, maintenance…) | Déjà fournies par ESPHome ; l'app n'en a pas besoin | Fournies par l'intégration | Redondant |
| Sécurité d'accès | Authentification HA par ingress, panneau réservé aux admins (`panel_admin: true`) | Authentification HA | Idem |
| Effort | Backend Python + frontend | Frontend Lit + intégration Python + HACS | Double |

**Choix : app avec ingress.** Seule réserve : il faut HA OS ou Supervised
(question ouverte n° 1). Si ce n'est pas le cas, le repli est un conteneur
Docker autonome avec le même backend et un lien dans la barre latérale via
`panel_iframe`, sans ingress.

### 4.2 Pile technique de l'app

- **Backend** : Python 3.13, `aiohttp` (HTTP + WebSocket), image de base
  `ghcr.io/home-assistant/{arch}-base-python`. Écoute sur `0.0.0.0:8099`
  en n'acceptant que `172.30.32.2` (passerelle ingress), URLs relatives,
  en-tête `X-Ingress-Path` pris en compte pour les WebSockets.
- **Frontend** : application monopage en Svelte 5 + Vite, CodeMirror 6
  (terminal et éditeur CML : coloration, autocomplétion, info-bulles tirées
  du YAML de référence), uPlot (graphiques temps réel légers). Construite à
  la génération de l'image (GitHub Actions → `ghcr.io`, images multi-arch
  `aarch64`/`amd64` comme le recommande HA ; construction locale possible
  en secours).
- **Config de l'app** (`options`/`schema`) : liste des ponts
  `[{nom, hôte, port}]`, dossier de stockage (défaut `/share/cool_muscle`),
  délai d'auto-sortie de maintenance, mode expert par défaut.
- **Stockage** : `/share/cool_muscle/fichiers/` (CML importés/édités),
  `/share/cool_muscle/sauvegardes/<pont>_<id>_<AAAAMMJJ-HHMMSS>.cml`
  (+ `.json` de métadonnées : firmware, K37, horodatage, auteur),
  `/share/cool_muscle/journal/<AAAA-MM>.jsonl` (toutes les écritures : qui,
  quand, quoi, écho, réponse). `/config` (app_config) pour les préférences.
- **Langue** : interface entièrement en français ; textes dans un fichier
  de traductions pour pouvoir ajouter l'anglais plus tard.

### 4.3 Modules du backend

```
cool_muscle_studio/
  bridge_client.py    connexion TCP à un pont, reconnexion, parse HELLO/RX/TX/EVT/ERR
  cml/
    lexer.py, parser.py   analyse d'une ligne / d'un fichier CML (banques, registres, K)
    reference.py          chargement de reference/cml_reference.yaml (noms, plages, unités)
    validate.py           validation des plages, détection K37, syntaxe des banques
  motor.py            modèle d'un moteur : identité, état Ux décodé, K, registres, banques
  session.py          transactions : envoyer une commande, attendre écho + réponse(s), délais
  transfer.py         téléchargement de fichier avec progression, reprise/annulation, relecture
  backup.py           sauvegarde/restauration/comparaison
  journal.py          journal des écritures (JSONL)
  api/                routes HTTP + WebSocket (flux terminal, état, graphiques)
  sim/cm1sim.py       simulateur de moteur (serveur TCP parlant le protocole cm1_bridge ET un mode « moteur nu » CR/LF)
```

Transactions : le moteur n'étiquette pas ses réponses. La session s'appuie
sur l'écho (actif par défaut) comme accusé de réception, puis sur la forme
attendue de la réponse (ex. `Px.1=` pour `?96.1`) avec un délai. Les lignes
spontanées (`Ux`, streaming K66) sont reconnues et routées vers l'état du
moteur sans perturber la transaction en cours. C'est précisément pour cela
que les captures réelles listées dans les questions ouvertes sont
indispensables avant l'étape 2.

### 4.4 Pages de l'interface

1. **Tableau de bord** : ponts, moteurs détectés (`?85.1` à `?85.15` avec
   délai court), état décodé, bouton **Arrêt d'urgence** présent sur toutes
   les pages (bandeau fixe) et **Annuler** (`*1`).
2. **Terminal** : historique (↑/↓, persistant), coloration, autocomplétion
   des commandes et des K avec description, horodatage, distinction
   écho / réponse / spontané / envoyé par l'ESP32, filtre, export (TXT/CSV).
3. **Fiche moteur** : identité (`?85`), température, état, position,
   vitesse, courant, erreur de position, E/S, analogique ; rafraîchissement
   réglable (désactivable), fonctionne en mode normal grâce à la liste
   blanche.
4. **Paramètres K** : tableau (n°, nom, description, valeur, défaut, plage,
   unité), édition avec validation, écriture des seuls paramètres modifiés
   avec confirmation, comparaison moteur ↔ fichier, avertissement K37 avec
   recalcul proposé des registres P/S.
5. **Fichiers CML** : explorateur de `/share/cool_muscle`, éditeur avec
   vérification de syntaxe, aperçu des différences moteur ↔ fichier avant
   envoi, téléchargement avec barre de progression, relecture
   (`?1000`, `?91`..`?94`, `?90`) et rapport, `$`.
6. **Sauvegardes** : sauvegarde complète horodatée, restauration (avec aperçu
   des différences), comparaison entre deux sauvegardes.
7. **Commandes** : jog, aller à une position, origine (`|`, `|1`, `|2`),
   activer/désactiver, banques (`[n`, `[Ln`, `]`, `]L`, `}`, `>`, `<`),
   sorties `O#`/`F#`. Toutes grisées hors mode maintenance et en alarme.
8. **Graphiques** : position, vitesse, courant en temps réel ; source au
   choix : interrogation périodique (`?96`/`?97`/`?98`) ou streaming
   K66/K67 (activé pour la durée de la session puis remis à 0 ; nécessite le
   mode maintenance puisqu'il modifie des K). Export CSV.

## 5. Mode maintenance, vu de bout en bout

```
App : MAINT ON ──► cm1_bridge : busy ? ──oui──► EVT MAINT REFUSED MOVING
                         │ non
                         ▼
              mode = maintenance, switch HA = on, EVT STATE
              lambda : ignore GPIO11/12, cmd_queue, polls, reconfig
                         │
App : commandes libres (écriture K, banques, mouvements manuels…)
                         │
App : MAINT OFF (ou déconnexion + délai, ou switch HA off)
                         ▼
              lambda : resync (?85, ?90 → K23/K37/K52, ?99, ?96),
              position lue = position courante, aucun mouvement,
              puis mode = normal, EVT STATE, switch HA = off
```

Jamais d'activation pendant un mouvement : c'est vérifié dans l'ESP32, pas
seulement dans l'app.

## 6. Exigences de sécurité → mesures

| Exigence | Mesure |
|---|---|
| Confirmation avant mouvement ou modification | Chaque commande est classée (`danger:` dans le YAML de référence) ; dialogue de confirmation pour `mouvement`, `configuration`, `memoire`, `arret` sauf `*` ; désactivable dans le terminal en mode expert (préférence par utilisateur, en-tête `X-Remote-User-Id`). |
| Aperçu des différences avant téléchargement | Lecture complète du moteur (K, registres, banques), diff ligne à ligne, résumé (ajouts, modifications, suppressions, K37). |
| Pas de mouvement sur un moteur en alarme | État Ux décodé en continu ; boutons de mouvement désactivés si bit d'alarme ; action explicite « Acquitter » (`*1`, `(`) avant. |
| Déconnexions pendant un transfert | Transfert découpé en lignes acquittées par écho ; sur coupure : arrêt, état « partiel » affiché avec la dernière ligne confirmée, propositions « reprendre à la ligne n », « relire le moteur », « annuler » ; jamais de `$` automatique après un transfert incomplet. |
| Journal des écritures | `journal.py` : toute ligne non-lecture envoyée (manuelle, transfert, restauration), avec utilisateur, pont, moteur, écho et réponse ; consultable dans l'app et exportable. |
| Jamais de test sur le vrai moteur sans accord | Développement et tests sur le simulateur ; chaque étape est montrée avant tout essai réel, que vous déclencherez. |

## 7. Simulateur et tests

- `cm1sim` : serveur TCP Python qui imite un ou plusieurs moteurs
  (ID 1..15) : écho, `Ux` automatiques, `?85`, `?90`, `?96..?99`, registres,
  banques (`B#`…`END`, `?1000`), `$`, `*`/`*1`, `(`/`)`, origine, mouvements
  simulés (profil trapézoïdal, `Ux=0` puis `Ux=8`), alarmes injectables,
  K66 streaming. Deux faces : « moteur nu » (CR/LF, pour tester le composant
  ESP32 via un port série virtuel) et « pont » (parle le protocole
  `cm1_bridge`, pour tester l'app sans ESP32). Les formats de réponse non
  documentés sont des hypothèses marquées comme telles, remplacées par les
  captures réelles dès réception.
- Tests `pytest` : lexer/parser CML (fichiers de la documentation : exemples
  Modbus, jog, analogique, figure-huit), validation des K (plages, chiffres
  N4N3N2N1, K37), transfert (succès, coupure au milieu, reprise, relecture
  divergente), décodage Ux, protocole `cm1_bridge`.
- Composant ESPHome : `esphome config` et `esphome compile` en CI (Docker) ;
  test d'intégration du serveur TCP contre `cm1sim` en « moteur nu » via
  un pont UART↔TCP de test si possible.

## 8. Arborescence du dépôt (prête pour Home Assistant)

```
HAoolMuscle/
  repository.yaml                 name / url / maintainer
  README.md                       français : installation, utilisation, maintenance, dépannage
  cool_muscle_studio/             l'app HA
    config.yaml                   slug, version, ingress, map share/app_config, options/schema
    build.yaml                    images de base par architecture
    Dockerfile
    DOCS.md, CHANGELOG.md, icon.png, logo.png, translations/fr.yaml
    backend/  frontend/  tests/
  esphome/
    cool-muscle.yaml              mis à jour, un seul fichier
    components/cm1_bridge/        __init__.py, cm1_bridge.cpp/.h, switch/, binary_sensor/, sensor/
  reference/cml_reference.yaml    la base de données (chargée par l'app et par les tests)
  docs/                           ce document, questions ouvertes, protocole TCP
  .github/workflows/              build des images, tests, esphome compile
```

Le dossier de travail est un dépôt Git local (branche `main`, un commit
initial) sans dépôt distant ; la publication sur GitHub fait partie de
l'étape 0 (nom et visibilité à confirmer).

## 9. Plan par étapes livrables

| Étape | Contenu | Ce que je vous montre |
|---|---|---|
| 0. Fondations | Dépôt Git, arborescence, `cml_reference.yaml` chargé par le code, lexer/parser CML, simulateur `cm1sim`, tests. Vos captures réelles intégrées au simulateur. | Tests verts, simulateur jouable avec `nc`. |
| 1. Pont et terminal | Composant `cm1_bridge`, `cool-muscle.yaml` mis à jour (config + compile OK), app minimale : connexion aux ponts, mode maintenance, terminal complet, arrêt d'urgence, journal. | App installée depuis le dépôt sur votre HA, terminal sur le simulateur ; puis, avec votre accord, flash de l'ESP32 et premier `?85` réel. |
| 2. Fiche moteur et K | Détection des moteurs, fiche en continu, éditeur K avec validation, comparaison, avertissement K37. | Fiche et éditeur sur simulateur puis sur le moteur (lecture seule d'abord). |
| 3. Fichiers et sauvegardes | Import/export, éditeur, diff, téléchargement avec progression et reprise, relecture, sauvegarde/restauration/comparaison. | Cycle complet sur simulateur, puis sauvegarde réelle du moteur (lecture seule), restauration sur votre feu vert. |
| 4. Graphiques | Position/vitesse/courant, interrogation ou K66/K67, export CSV. | Courbes d'un mouvement simulé puis réel. |
| 5. Finitions | README français, DOCS de l'app, multi-ponts, revue sécurité, release 1.0. | Dépôt prêt à publier. |

Chaque étape est validée par vous avant la suivante, et aucun essai sur le
vrai moteur n'a lieu sans votre demande explicite.

## 10. Ce qu'il faut trancher avant l'étape 0

Voir [`docs/questions-ouvertes.md`](questions-ouvertes.md) : type
d'installation HA, nom du dépôt GitHub, comportement à la sortie de
maintenance, auto-sortie en cas de déconnexion, choix du frontend, et la
liste des captures à réaliser avec le champ « Commande CML » existant.
