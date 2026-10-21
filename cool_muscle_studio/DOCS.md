# Cool Muscle Studio

Configuration, programmation et diagnostic des servomoteurs Cool Muscle CM1
depuis Home Assistant, via un pont ESP32-S3 (ESPHome, composant `cm1_bridge`).

## Installation

1. Flasher `esphome/cool-muscle.yaml` (dépôt du projet) sur l'ESP32 depuis le
   tableau de bord ESPHome. Le composant `cm1_bridge` est téléchargé
   automatiquement depuis GitHub (`external_components`).
2. Installer cette app depuis le dépôt du projet, puis renseigner l'adresse du
   pont dans les options (`hote` : nom mDNS `cool-muscle.local` ou adresse IP,
   `port` : 6638).
3. Démarrer l'app et ouvrir « Cool Muscle » dans la barre latérale.

## Options

| Option | Description |
|---|---|
| `ponts` | Liste des ponts ESP32 : `nom`, `hote` (de préférence l'adresse IP de l'ESP32 ; `cool-muscle.local` n'est pas toujours résolu depuis le conteneur), `port` (6638 par défaut). |
| `dossier` | Dossier des fichiers CML, sauvegardes et journaux (`/share/cool_muscle`). |
| `sortie_auto_maintenance_s` | Pour information : le délai de sortie automatique est réglé dans le YAML ESPHome (`maintenance_timeout`). |
| `mode_expert` | Désactive par défaut les confirmations dans le terminal (chaque navigateur peut aussi le régler). |

## Terminal

- `↑`/`↓` : historique (conservé par navigateur et par pont) ; `Tab` : accepte
  la suggestion ; `Ctrl+Échap` : arrêt d'urgence.
- Lignes : `TX ESP32` = commande envoyée par la logique embarquée,
  `TX C1 (moi)` = envoyée par ce terminal, `RX écho` = écho du moteur,
  `RX` = réponse, les lignes `Ux` sont mises en évidence.
- En mode normal, seules les lectures (`?…`, `K37.1`, `P15.1`, `_SKH`) et
  l'arrêt d'urgence sont acceptées. Les écritures exigent le mode maintenance.
- Les commandes qui font bouger le moteur ou modifient sa configuration
  demandent une confirmation, sauf en mode expert. Toutes les écritures sont
  journalisées dans `<dossier>/journal/AAAA-MM.jsonl`.

## Mode maintenance

Pendant le mode maintenance, l'ESP32 ignore les commandes du robot et ne
parle plus au moteur de lui-même : l'application a la main. Il est impossible
de l'activer pendant un mouvement ou en alarme. En sortant, l'ESP32 relit
l'état et la configuration du moteur, puis reprend son fonctionnement normal
sans faire bouger le moteur. Le mode est visible et pilotable dans Home
Assistant par l'entité « Mode maintenance » du pont. Si l'app se déconnecte,
le pont quitte seul le mode maintenance après `maintenance_timeout` (60 s).

## Dépannage

- **« déconnecté »** dans la barre : vérifier `hote`/`port`, que l'ESP32 est
  joignable (`ping cool-muscle.local`) et que `allowed_ips` du YAML, s'il est
  défini, inclut l'adresse de Home Assistant.
- **« écriture refusée : le pont n'est pas en mode maintenance »** : activer
  le mode maintenance (bouton ou entité HA).
- **« maintenance refusée : mouvement en cours »** : attendre la fin du
  mouvement ; en alarme, acquitter d'abord (`*1`, `(`).
- **Aucun moteur détecté** : vérifier l'alimentation 24 V, K52=1 et la
  vitesse 38400 ; le journal ESPHome (`[cm1_bridge]`) montre le trafic.
