# Installation dans Home Assistant et premier essai en lecture seule

Ce guide suppose que le dépôt est publié sur GitHub (`Nailaky/HAoolMuscle`,
branche `main`) et que Home Assistant est en version OS ou Supervised.

## 1. Flasher l'ESP32

1. Dans le tableau de bord ESPHome, ouvrir la configuration existante
   `cool-muscle` et remplacer son contenu par `esphome/cool-muscle.yaml` du
   dépôt, en **conservant votre clé API** (`api: encryption: key:`) et vos
   secrets Wi-Fi (`!secret wifi_ssid`, `!secret wifi_password`).
2. *Install* → *Wirelessly* (OTA). ESPHome télécharge le composant
   `cm1_bridge` depuis GitHub (`external_components`), compile, puis flashe.
   La première compilation est longue (esp-idf).
3. Attendre le redémarrage, puis ouvrir *Logs*. Vous devez voir :
   - `[cm1_bridge] CM1 Bridge: Port TCP : 6638` ;
   - la séquence de démarrage habituelle (`> [LOCAL] ?85.1`, `< CM1 ID1 FW:…`,
     `> [LOCAL] ?90.1`, les lignes `K…`, puis `(.1`, `|2.1`) ;
   - l'état « Prêt » et aucun mouvement.

   Le moteur ne bouge pas au démarrage, comme avant. La logique robot (entrées
   GPIO11/12) fonctionne exactement comme avec l'ancien YAML.

4. Dans Home Assistant, l'appareil « Cool Muscle » a trois entités de plus :
   **Mode maintenance** (interrupteur), **Application connectée**,
   **Clients connectés**. Les anciennes entités gardent leurs noms.

Si la compilation échoue sur `external_components`, vérifier que le dépôt est
public ou que ESPHome a accès à GitHub, et que `path: esphome/components` est
bien présent.

## 2. Installer l'app

1. *Paramètres → Apps → Installer une app* (ou *Boutique des add-ons* selon
   la version), menu ⋮ en haut à droite → *Dépôts*, coller
   `https://github.com/Nailaky/HAoolMuscle`, *Ajouter*.
2. Ouvrir **Cool Muscle Studio** dans la liste, *Installer*. Le Supervisor
   construit l'image sur l'appareil (quelques minutes sur un Raspberry Pi).
3. Onglet *Configuration* :

   ```yaml
   ponts:
     - nom: Cool Muscle
       hote: 192.168.x.y      # adresse IP de l'ESP32 (réservation DHCP conseillée)
       port: 6638
   dossier: /share/cool_muscle
   ```

   Utilisez l'adresse IP plutôt que `cool-muscle.local` : la résolution mDNS
   n'est pas garantie depuis le conteneur de l'app. L'adresse se lit dans
   *Paramètres → Appareils → ESPHome → Cool Muscle* ou dans les logs ESPHome.
4. *Démarrer*, activer *Afficher dans la barre latérale*, puis ouvrir
   **Cool Muscle** dans la barre latérale.

La barre du haut doit afficher **connecté** et **normal**. Si « déconnecté »
persiste : vérifier l'IP, le port 6638, et que l'entité « Application
connectée » passe à *on* quand l'app démarre. Le journal de l'app
(*Paramètres → Apps → Cool Muscle Studio → Journal*) indique l'erreur de
connexion.

## 3. Premier essai en lecture seule

Tout ce qui suit passe en **mode normal** : aucune écriture, aucun mouvement,
la logique robot reste active. Le pont refuse de lui-même toute écriture dans
ce mode (`ERREUR FORBIDDEN`).

1. Cliquer **Détecter les moteurs** : le moteur 1 doit apparaître avec sa
   bannière (`FW:…`, `HW:…`).
2. Dans le terminal, envoyer dans l'ordre les commandes de la liste des
   captures (`docs/questions-ouvertes.md`, section B), une par une :

   ```
   K55.1
   ?85.1
   ?90.1
   ?.1
   ?P.1
   ?91.1
   ?92.1
   ?93.1
   ?94.1
   ?95.1
   ?96.1
   ?97.1
   ?98.1
   ?99.1
   ?70.1
   ?71.1
   ?74.1
   ?51.1
   ?52.1
   P15.1
   V1.1
   ?1000.1
   ?0.1
   _SKH.1
   ZZZ.1
   ```

   Observer en particulier la forme de l'écho (ligne `RX écho`), le format
   des lignes de `?90.1` et de `?1000.1`, et la réponse à `ZZZ.1` (message
   d'erreur). Ces formats sont les « hypothèses » du simulateur à remplacer.
3. Faire un aller-retour avec le robot (ou les boutons « Aller à 180° » /
   « Retour à 0° » de Home Assistant) en gardant le terminal ouvert : les
   lignes `TX ESP32` montrent ce que l'ESP32 envoie, les `Ux` le déroulement
   du mouvement, et le badge « en mouvement » doit s'allumer.
4. Pendant ce mouvement, cliquer **Mode maintenance** : le pont doit refuser
   (`maintenance refusée : mouvement en cours`). Moteur à l'arrêt, réessayer :
   le badge passe à **MAINTENANCE** et l'entité HA « Mode maintenance » à
   *on*. Vérifier que les entrées robot sont ignorées (l'état affiche
   « Maintenance »). Cliquer **Quitter la maintenance** : l'ESP32 relit
   `?85`, `?90`, `?99`, `?96` sans bouger et l'état revient à « Prêt ».
5. Cliquer **Exporter** et m'envoyer le fichier texte : il contient toutes
   les captures horodatées. Je mettrai à jour la référence et le simulateur.

Les commandes `K55.1=0` (valeur hors plage) et `K55.1=7`, ainsi que le test de
streaming K66, sont des écritures : à faire seulement si vous le décidez, en
mode maintenance, après la lecture seule.

## 4. En cas de problème

| Symptôme | Cause probable | Action |
|---|---|---|
| ESPHome : `Component cm1_bridge … not found` | dépôt inaccessible ou `path` incorrect | vérifier `external_components` dans le YAML, dépôt public |
| Logs ESPHome : `bind() a échoué` | port 6638 déjà utilisé | changer `port:` dans `cm1_bridge:` et dans l'app |
| App « déconnecté » | IP ou port erroné, `allowed_ips` restrictif | tester `nc <ip> 6638` puis `PING` depuis un PC du même réseau |
| `ERREUR FORBIDDEN` | écriture en mode normal | activer le mode maintenance |
| Rien ne répond au moteur | K20 ou K52 changés, câblage | retirer l'alimentation 24 V 10 s, relancer, comparer avec l'ancien YAML |
| « Prêt (configuration corrigée après maintenance) » | un des K23/K37/K52 a été modifié en maintenance | normal : l'ESP32 a remis sa valeur |

Pour revenir à l'ancien fonctionnement, reflasher l'ancien YAML ; l'app
affichera simplement « déconnecté ».
