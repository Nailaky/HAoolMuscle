"""Simulateur de moteur Cool Muscle CM1 (cm1sim).

Deux faces :
- « moteur nu » : serveur TCP qui se comporte comme le port série du moteur
  (commandes terminées par CR, réponses CR LF) ;
- « pont » : serveur TCP qui parle le protocole du composant ESPHome
  cm1_bridge (voir cmstudio.protocol), avec mode maintenance et liste blanche.

Les formats de réponse non documentés sont des hypothèses centralisées dans
``formats.py`` et remplacées par les captures réelles dès réception.
"""

from .chain import MotorChain
from .motor import MotorSim
from .server import Simulator

__all__ = ["MotorChain", "MotorSim", "Simulator"]
