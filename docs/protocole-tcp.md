# Protocole TCP entre l'application et le pont ESP32 (`cm1_bridge`)

Version 1. Port par défaut : 6638. Texte UTF-8, une ligne par message,
terminée par LF (`\n`). Le pont accepte aussi CR LF en entrée. Lisible avec
`nc` ou `telnet`. Implémentations : `cmstudio/protocol.py` (côté app et
simulateur), `esphome/components/cm1_bridge` (côté ESP32, étape 1).

## Client → pont

| Message | Effet |
|---|---|
| `TX <ligne CML>` | Envoie la ligne au moteur (le pont ajoute le CR). 60 caractères max. En mode normal, seules les lectures et l'arrêt d'urgence sont acceptées (voir liste blanche). |
| `MAINT ON` | Demande le mode maintenance. Refusé si un mouvement est en cours, pendant le démarrage ou en alarme. |
| `MAINT OFF` | Quitte le mode maintenance ; le pont resynchronise sa logique (relecture `?90`, `?99`, `?96`). |
| `STATUS` | Demande l'état courant (réponse `EVT … STATE`). |
| `PING` | Réponse `PONG`. |

Liste blanche du mode normal (chaque instruction d'une ligne, séparées par des
virgules, doit en faire partie) :

- requêtes `?…` (`?`, `?96.1`, `?1000`, `?P`…) ;
- lecture d'un registre sans `=` (`P15.1`, `K37`, `V1.2`) ;
- `_SKH` sans `=` ;
- `*` et `*1` (arrêt d'urgence et annulation), toujours acceptés.

## Pont → client

| Message | Sens |
|---|---|
| `HELLO <version> <mode> <busy>` | À la connexion. `mode` = `NORMAL` ou `MAINT`, `busy` = `0`/`1`. |
| `RX <ms> <ligne>` | Ligne reçue du moteur (sans CR/LF). Inclut les échos, les réponses et les messages spontanés (`Ux`, streaming K66). |
| `TX <ms> <origine> <ligne>` | Ligne envoyée au moteur. `origine` = `LOCAL` (logique robot de l'ESP32) ou `C<n>` (client n). Permet de distinguer l'écho d'une commande de l'ESP32 de celui d'une commande de l'utilisateur. |
| `EVT <ms> STATE <mode> <busy>` | Changement de mode ou d'occupation (début/fin de mouvement). |
| `EVT <ms> MAINT REFUSED <raison>` | Entrée en maintenance refusée : `MOVING`, `STARTUP`, `ALARM`. |
| `ERR <ms> <code> <texte>` | Ligne refusée : `FORBIDDEN` (hors liste blanche en mode normal), `TOOLONG`, `QUEUE_FULL`, `BADCMD` (message client inconnu). |
| `PONG` | Réponse à `PING`. |

`<ms>` : millisecondes depuis le démarrage du pont (`millis()` sur l'ESP32).
L'application y ajoute sa propre horloge murale à la réception.

## Règles

- Le pont diffuse chaque ligne `RX` et `TX` à tous les clients connectés.
- Une seule file de sortie vers le moteur, espacement minimal entre lignes
  (3 ms par défaut) ; la logique robot est prioritaire en mode normal.
- En mode maintenance, la logique robot est suspendue : entrées GPIO
  ignorées, aucun envoi `LOCAL`.
- Si tous les clients se déconnectent en mode maintenance, le pont revient
  en mode normal après un délai (60 s par défaut, 0 = jamais ; question
  ouverte n° 4).
- Quatre clients au maximum ; `allowed_ips` côté ESPHome limite les sources.

## Exemple de session

```
← HELLO 1 NORMAL 0
→ TX ?99.1
← TX 12034 C1 ?99.1
← RX 12036 ?99.1
← RX 12040 Ux.1=8
→ TX K55.1=5
← ERR 12100 FORBIDDEN K55.1=5
→ MAINT ON
← EVT 12200 STATE MAINT 0
→ TX K55.1=5
← TX 12210 C1 K55.1=5
← RX 12212 K55.1=5
→ MAINT OFF
← EVT 12300 STATE NORMAL 0
← TX 12301 LOCAL ?90.1
← RX 12303 ?90.1
← RX 12305 K14.1=0
…
```
