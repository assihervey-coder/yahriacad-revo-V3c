# ESP32-WROOM-32E — Résumé datasheet (Espressif)

## Caractéristiques clés
- MCU : Xtensa LX6 dual-core 240 MHz, 520 KB SRAM, 448 KB ROM.
- WiFi 802.11 b/g/n 2.4 GHz + BLE 4.2 BR/EDR.
- Tension d'alimentation : 3.0 V à 3.6 V (typ. 3.3 V) — logique NON 5V-tolérante.
- Courant : ~80-240 mA en TX WiFi (pics à 500 mA) → prévoir un régulateur
  capable d'au moins 500 mA et un condensateur de 470 µF+ près du module.
- Température : -40 à +85 °C.

## Pins critiques
- EN : reset actif bas, pull-up 10 kΩ + condensateur 1 µF vers GND.
- IO0 : boot strapping (haut = flash boot normal) ; pull-up 10 kΩ.
- GPIO34/35/36/39 : entrées SEULEMENT (pas de pull-up internes).
- GPIO6-11 : reliés à la flash SPI interne — NE PAS UTILISER.
- Antenne PCB intégrée : garder une zone libre sans cuivre (keepout) de
  8-10 mm autour de l'antenne, l'antenne en bord de carte.

## Découplage
- 100 nF sur chaque pin VDD + 10 µF bulk + 470 µF si WiFi actif.
- 22 µF minimum sur VDD33 selon datasheet Espressif (bloc B1).