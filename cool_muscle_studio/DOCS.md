# Cool Muscle Studio

Configuration, programmation et diagnostic des servomoteurs Cool Muscle CM1
depuis Home Assistant, via un pont ESP32-S3 (ESPHome, composant `cm1_bridge`).

## État

Version 0.0.1 : squelette. L'interface web arrive avec la version 0.1
(étape 1 : pont série et terminal).

## Options

| Option | Description |
|---|---|
| `ponts` | Liste des ponts ESP32 : `nom`, `hote` (nom mDNS ou adresse IP), `port` (6638 par défaut). |
| `dossier` | Dossier des fichiers CML, sauvegardes et journaux (`/share/cool_muscle`). |
| `sortie_auto_maintenance_s` | Délai après lequel le pont quitte seul le mode maintenance si l'app est déconnectée (0 = jamais). |
| `mode_expert` | Désactive les confirmations dans le terminal. |

## Mode maintenance

Pendant le mode maintenance, l'ESP32 ignore les commandes du robot et ne
parle plus au moteur de lui-même : l'application a la main. Il est impossible
de l'activer pendant un mouvement. En sortant, l'ESP32 relit l'état et la
configuration du moteur, puis reprend son fonctionnement normal. Le mode est
visible dans Home Assistant par l'entité « Mode maintenance » du pont.

## Dépannage

À compléter à l'étape 1.
