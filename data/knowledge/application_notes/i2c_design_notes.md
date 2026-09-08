# I2C — Notes de conception

- Bus open-drain : résistances de pull-up OBLIGATOIRES sur SDA et SCL.
  Valeur typique 4.7 kΩ à 3.3 V (2.2 kΩ pour un bus très chargé à 400 kHz,
  10 kΩ acceptable pour un bus court à 100 kHz).
- Vitesse : 100 kHz (standard), 400 kHz (fast), 1 MHz (fast+).
- Longueur : garder < 30 cm ; au-delà, réduire la capacité ou utiliser un
  buffer (P82B96).
- Mixed voltage : un device 5V sur un bus 3.3V nécessite un level shifter
  (ex : PCA9306) — les pins 3.3V ne sont pas 5V-tolérantes sur la plupart des MCU.
- Pull-up sur une seule paire de résistances pour tout le bus (pas une paire
  par device).