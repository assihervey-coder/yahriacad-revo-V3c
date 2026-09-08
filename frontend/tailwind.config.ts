import type { Config } from "tailwindcss";

/** Palette V3 : fond nuit, panneaux anthracite, accents cyan + violet. */
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        base: "#0B0E14", // fond global
        panel: {
          DEFAULT: "#12161F", // panneaux / cartes
          soft: "#161B26", // variante survol / blocs imbriqués
          border: "#232A38", // bordures discrètes
        },
        accent: {
          cyan: "#22D3EE",
          violet: "#A78BFA",
        },
        ink: {
          DEFAULT: "#E5E7EB", // texte principal
          dim: "#9CA3AF", // texte secondaire
        },
      },
      borderRadius: {
        // rounded-xl = 12px déjà fourni par Tailwind ; alias explicite :
        panel: "12px",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        panel: "0 10px 30px -12px rgba(0,0,0,0.55)",
        glow: "0 0 24px -6px rgba(34,211,238,0.35)",
      },
    },
  },
  plugins: [],
};

export default config;
