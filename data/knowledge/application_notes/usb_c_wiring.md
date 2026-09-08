# USB-C — Notes de câblage (appareil UFP 2.0)

## Câblage minimal (USB 2.0 device)
- VBUS : 5V, condensateur de 1 µF côté récepteur ; diode TVS recommandée.
- CC1 / CC2 : résistances pull-down 5.1 kΩ (Rd) SUR CHAQUE pin CC pour un
  device sink — sans Rd, aucune source n'alimentera VBUS.
- DP / DM : paire différentielle 90 Ω, matching de longueur intra-paire
  ±0.5 mm, longueur totale < 100 mm idéalement, plan de masse continu dessous.
- Dconnector : USB-C possède 2x DP, 2x DM, 2x SBU — en device 2.0, connecter
  DP-A4/A5 et DP-B4/B5 ensemble, DM-A6/A7 et DM-B6/B7 ensemble (soudures en
  A5<->B5 pour CC via 2 résistances séparées).

## Erreurs fréquentes
- Oublier le pull-down Rd sur CC → la carte ne reçoit jamais de power.
- Router DP/DM à travers un split de plan → crosstalk et EMI.
- Vias de test sur CC à moins de 5.1 kΩ au GND par erreur.