/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Le viewer three.js est importé dynamiquement (ssr:false) : pas de transpile nécessaire,
  // webpack gère three/examples/jsm nativement.
  eslint: {
    // Le lint est lancé séparément (npm run lint) ; build non bloqué par ESLint.
    ignoreDuringBuilds: true,
  },
};

export default nextConfig;
