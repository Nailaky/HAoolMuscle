# Questions ouvertes et captures à réaliser

Mis à jour le 2026-10-21. Les réponses conditionnent l'étape 0 ; les captures
conditionnent l'étape 2 (le terminal de l'étape 1 fonctionne sans).

## A. Décisions à prendre

1. **Type d'installation Home Assistant.** L'app avec ingress exige HA OS ou
   HA Supervised. Est-ce votre cas ? Sinon je propose un conteneur Docker
   autonome + `panel_iframe` (même backend, sans ingress).
2. **Dépôt GitHub.** Nom proposé : `HAoolMuscle` (nom du dossier) ou
   `cool-muscle-studio` ; public ou privé ; propriétaire. Il sert à la fois
   de dépôt d'apps HA et de source `external_components` pour ESPHome.
3. **Sortie du mode maintenance.** Après resynchronisation, si la position
   lue ne correspond ni à 0° ni à 180° (par exemple après un jog manuel),
   proposition : ne pas bouger, afficher « Position hors consigne » et
   attendre le prochain ordre du robot, qui ramène le moteur en position.
   Alternative : revenir automatiquement à la dernière consigne. Laquelle ?
4. **Auto-sortie de maintenance.** Si tous les clients TCP se déconnectent
   (coupure Wi-Fi de HA, app arrêtée) alors que le mode maintenance est
   actif, proposition : sortie automatique après 60 s (réglable, 0 = jamais).
   D'accord ?
5. **Origine `|2` par l'app.** Si l'utilisateur redéfinit l'origine depuis
   l'app, la correspondance degrés/impulsions de l'ESP32 change. Proposition :
   l'ESP32 considère la position lue à la sortie de maintenance comme sa
   nouvelle référence 0° si et seulement si un `|2` a été envoyé pendant la
   session (l'app le signale) ; sinon rien ne change. D'accord ?
6. **Frontend.** Décision prise à l'étape 1 : pages HTML/JS sans étape de
   build (servies telles quelles par l'app), ce qui simplifie la construction
   de l'image par le Supervisor. Les graphiques utiliseront une bibliothèque
   légère embarquée (uPlot). À reconsidérer si l'éditeur CML devient trop
   complexe.
7. **Multi-clients.** Plusieurs onglets/navigateurs sur le même pont doivent-ils
   pouvoir émettre en même temps en maintenance, ou un seul « pilote » à la
   fois (les autres en lecture) ? Je recommande un seul pilote, avec reprise
   de main explicite.
8. **Port TCP** du pont : 6638 (convention des stream servers ESPHome) ou
   autre ?
9. **Chaîne de moteurs.** Un seul moteur aujourd'hui. Avez-vous un second
   moteur pour tester la daisy chain, ou on valide le multi-moteurs sur
   simulateur seulement ?
10. **Comptes HA.** Le panneau est réservé aux administrateurs
    (`panel_admin: true`). D'accord ?

## B. Captures à réaliser avec le champ « Commande CML » actuel

Envoyer chaque commande depuis Home Assistant et relever les lignes dans les
logs ESPHome (niveau DEBUG, lignes `< …`) ou le capteur « Dernière réponse
moteur ». Moteur à l'arrêt, robot au repos. Aucune de ces commandes ne fait
bouger le moteur, sauf la série marquée ⚠.

| N° | Commande | Ce que je cherche |
|---|---|---|
| 1 | `K55.1` | forme exacte de l'écho et de la réponse d'une lecture de K |
| 2 | `K55.1=5` (valeur déjà en place) | écho d'une écriture, réponse éventuelle |
| 3 | `?85.1` | bannière complète ID / FW / HW |
| 4 | `?90.1` | format complet : une ligne par K ? ordre ? suffixe `.1` ? combien de lignes ? |
| 5 | `?.1` puis `?P.1` | format de `?` et de `?x` |
| 6 | `?91.1` `?92.1` `?93.1` `?94.1` | une ligne par registre ? |
| 7 | `?95.1` `?96.1` `?97.1` `?98.1` `?99.1` | préfixes (`Ex`, `Px`, `Sx`, `Tx`/`Ix`, `Ux`) |
| 8 | `?70.1` `?71.1` `?74.1` `?51.1` `?52.1` | formats E/S, température, analogique |
| 9 | `P15.1` puis `V1.1` | lecture simple d'un registre, registre vide ou chaîne |
| 10 | `?1000.1` | format des banques et ligne du nombre de pas (même si vide) |
| 11 | `?0.1` | format d'une banque seule |
| 12 | `_SKH.1` | réponse à la lecture |
| 13 | `ZZZ.1` puis `K55.1=0` | message d'erreur de syntaxe, message de valeur hors plage |
| 14 | `$.1` | réponse exacte (« Saved.1 » ?) |
| 15 ⚠ | `K66.1=2` puis `K67.1=20`, un aller-retour robot, puis `K66.1=0` | format des lignes de streaming pendant un mouvement |
| 16 | (optionnel) écriture d'une petite banque : `B30.1`, `T0.1`, `END.1`, puis `?30.1` et `?1000.1`, puis `B30.1`, `END.1` pour la vider | écho ligne par ligne, format d'une banque relue, `?17..?30` acceptés ? |

Si le capteur « Dernière réponse moteur » ne garde que la dernière ligne, les
logs ESPHome (console du tableau de bord ESPHome) montrent toutes les lignes
avec le préfixe `[cm1] <`.

## C. Contradictions relevées dans la documentation (déjà notées dans le YAML)

- K61 : max 3001 (page K, 3001 = infini) contre 30000/30001 (page Push Move,
  RT3).
- K22, K60, K87 : valeur par défaut hors de la plage documentée.
- K49 : unité « 100 Pulses » (page K) contre « 100 imp/s » (note
  d'application).
- K72 : « non implémenté » (page K) contre seuil de tension de régénération
  (RT3 et page Status).
- K51, K68, K76..K78 : présents dans le RT3 seulement.
- `]1` : « pause de ce seul moteur » dans le RT3, absent du User Guide.
- `?0..?16` pour 30 banques.
- `?98` : « Iq moyenné » (RT3) contre « couple Tx » (table Modbus).
- Tableau `?85..?99` du PDF décalé d'une ligne (artefact de mise en page) :
  la page web et le RT3 font foi.
- Statusword (page Direct Control) ajoute des bits B6, B14, B15 à `?99`
  absents de la liste classique.
