# Journal des modifications

## 0.3.0 (2026-10-21)

- Panneau « Commandes rapides » : lecture de K37 pour convertir degrés,
  tr/min et tr/s² en impulsions ; aller à une position, jog ± d'un pas,
  rotation continue dans les deux sens, stop, activer/désactiver, recherche
  d'origine, aller à 0, origine ici, lecture de la position. Chaque action
  est une courte séquence envoyée ligne par ligne avec accusé par l'écho, en
  mode maintenance, avec confirmation (sauf mode expert) et journal.
- Panneau « Configuration du moteur » : export de la configuration complète
  (`?85`, `?90`, tous les registres, `?1000`) en fichier `.cml` horodaté
  réimportable, plus un `.json` avec les lignes brutes, dans
  `<dossier>/sauvegardes` ; liste et téléchargement des sauvegardes. Lecture
  seule, possible en mode normal. Les K de liaison (K20, K23, K52, K62, K65,
  K70) sont exportés en commentaire.
- Validation : la valeur d'usine documentée d'un K est acceptée même quand la
  documentation lui donne une plage incompatible (K22, K60, K87, K88).

## 0.2.0 (2026-10-21)

- Panneau « Fichier CML » : import d'un fichier `.cml`, `.cmp` ou `.txt`,
  prétraitement CMP (commentaires, `#define`, `var`, constantes dans les
  banques hissées dans des registres N comme Control Room), analyse et
  validation, puis envoi ligne par ligne en mode maintenance avec accusé par
  l'écho du moteur, barre de progression, annulation et journal. Le transfert
  s'arrête à la première ligne non confirmée et indique le nombre de lignes
  confirmées. La relecture de vérification arrivera à l'étape 3.

## 0.1.1 (2026-10-21)

- Images pré-construites (amd64, aarch64) publiées sur ghcr.io par GitHub
  Actions : le Supervisor n'a plus besoin de construire l'image sur
  l'appareil.

## 0.1.0 (étape 1, 2026-10-21)

- Composant ESPHome `cm1_bridge` : pont TCP arbitré (port 6638), mode
  maintenance (entité switch), liste blanche en mode normal, horodatage,
  capteurs « Application connectée » et « Clients connectés ».
- `cool-muscle.yaml` : lecture du moteur via `cm1_bridge`, suspension de la
  logique robot en maintenance, resynchronisation à la sortie sans mouvement.
- App : serveur web (aiohttp, ingress), connexion à un ou plusieurs ponts avec
  reconnexion, terminal (historique, coloration, autocomplétion des commandes
  et des K avec description, horodatage, distinction écho / réponse / trafic
  de l'ESP32, filtres, export), arrêt d'urgence permanent, mode maintenance,
  détection des moteurs, confirmation des commandes sensibles (mode expert
  pour la désactiver), journal des écritures.

## 0.0.1 (étape 0, 2026-10-21)

- Squelette de l'app (non fonctionnelle : le serveur web arrive à l'étape 1).
- Bibliothèque `cmstudio` : référence CML, parseur, CMP, validateur, décodage Ux,
  protocole TCP du pont, simulateur `cm1sim`, tests.
