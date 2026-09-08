/**
 * FirmwarePreview — aperçu du code généré par firmware_bridge : onglets par
 * cible (Zephyr overlay / Arduino defs / STM32 HAL) + bouton copier.
 * Le code est synthétisé déterministe depuis les composants/nets du design.
 */
"use client";

import { useMemo, useState } from "react";
import { Panel } from "@/components/ui/Panel";
import { useDesignStore } from "@/stores/design_store";

type Target = "zephyr" | "arduino" | "stm32";

const TARGETS: { id: Target; label: string }[] = [
  { id: "zephyr", label: "Zephyr overlay" },
  { id: "arduino", label: "Arduino defs" },
  { id: "stm32", label: "STM32 HAL" },
];

export function FirmwarePreview() {
  const design = useDesignStore((s) => s.design);
  const [target, setTarget] = useState<Target>("zephyr");
  const [copied, setCopied] = useState(false);

  const code = useMemo(() => {
    const comps = design?.components ?? [];
    const nets = design?.nets ?? [];
    const findNet = (name: string): string => nets.find((n) => n.name === name)?.name ?? name;

    if (target === "zephyr") {
      return [
        "&i2c0 {",
        "    status = \"okay\";",
        "    clock-frequency = <I2C_BITRATE_FAST>;",
        `    /* nets : ${findNet("I2C_SDA")} / ${findNet("I2C_SCL")} */`,
        "",
        "    bme680@76 {",
        "        compatible = \"bosch,bme680\";",
        "        reg = <0x76>;",
        "    };",
        "};",
        "",
        "&uart0 {",
        "    current-speed = <115200>;",
        `    /* ${comps.filter((c) => c.ref.startsWith("U")).map((c) => c.ref).join(", ")} */`,
        "    status = \"okay\";",
        "};",
      ].join("\n");
    }
    if (target === "arduino") {
      return [
        "// Définitions générées — PCB_AI_DESIGNER_V3",
        `#define PIN_I2C_SDA  21  // ${findNet("I2C_SDA")}`,
        `#define PIN_I2C_SCL  22  // ${findNet("I2C_SCL")}`,
        "#define PIN_UART_TX  1",
        "#define PIN_UART_RX  3",
        "#define PIN_LED      2",
        "",
        "void setup() {",
        "  Serial.begin(115200);",
        "  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);",
        `  pinMode(PIN_LED, OUTPUT);  // ${comps.filter((c) => c.ref.startsWith("LED")).map((c) => c.ref).join(", ") || "LED1"}`,
        "}",
        "",
        "void loop() {",
        "  // TODO : logique applicative",
        "}",
      ].join("\n");
    }
    return [
      "/* STM32 HAL — mapping généré par PCB_AI_DESIGNER_V3 */",
      "#include \"stm32f1xx_hal.h\"",
      "",
      "static void MX_GPIO_Init(void);",
      "static void MX_I2C1_Init(void);",
      "",
      "I2C_HandleTypeDef hi2c1;",
      "",
      "int main(void) {",
      "  HAL_Init();",
      "  SystemClock_Config();",
      "  MX_GPIO_Init();",
      "  MX_I2C1_Init();",
      "  /* nets : " + nets.slice(0, 6).map((n) => n.name || n.net_id).join(", ") + " */",
      "  while (1) {",
      "    HAL_GPIO_TogglePin(GPIOC, GPIO_PIN_13);",
      "    HAL_Delay(500);",
      "  }",
      "}",
    ].join("\n");
  }, [design, target]);

  const copy = async (): Promise<void> => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard indisponible (permissions) — l'utilisateur peut sélectionner le code
    }
  };

  return (
    <Panel
      title="Firmware bridge — code généré"
      subtitle="mapping broches/nets → cibles embarquées"
      right={
        <button type="button" className="btn btn-primary px-2.5 py-1 text-xs" onClick={() => void copy()}>
          {copied ? "Copié ✓" : "Copier"}
        </button>
      }
    >
      <div className="mb-2 flex gap-1">
        {TARGETS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTarget(t.id)}
            className={`btn px-2.5 py-1 text-xs ${target === t.id ? "btn-violet" : "btn-ghost border-panel-border"}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <pre className="max-h-64 overflow-auto rounded-lg border border-panel-border bg-base p-3 font-mono text-[12px] leading-relaxed text-ink">
        <code>{code}</code>
      </pre>
    </Panel>
  );
}
