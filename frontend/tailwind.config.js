/**
 * Hyper-Saturated Fluid.
 *
 * One shout colour carrying the brand, deep void balancing it, glass for
 * anything that floats. The named radii are extreme on purpose - an 8px corner
 * anywhere in this UI reads as a different product.
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        cyber: {
          DEFAULT: "#FDE047",
          deep: "#EAB308",
          wash: "#FEF9C3",
        },
        onyx: "#0A0A0A",
        charcoal: "#171717",
        graphite: "#262626",
        seam: "#333333",
        // Semantic, for data only. Kept deliberately narrow so charts read as
        // one system instead of a paint chart.
        signal: {
          loss: "#FF5D5D",
          natural: "#8B8B8B",
          incremental: "#FDE047",
          calm: "#4ADE80",
          info: "#60A5FA",
        },
      },
      fontFamily: {
        sans: ["Inter Variable", "Inter", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      borderRadius: {
        liquid: "120px",
        "liquid-sm": "40px",
        glass: "32px",
      },
      letterSpacing: { label: "0.18em" },
      transitionTimingFunction: {
        liquid: "cubic-bezier(0.22, 1, 0.36, 1)",
      },
      keyframes: {
        float: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-6px)" },
        },
        rise: {
          from: { opacity: "0", transform: "translateY(18px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        sweep: {
          from: { transform: "translateX(-100%)" },
          to: { transform: "translateX(200%)" },
        },
      },
      animation: {
        float: "float 7s cubic-bezier(0.22, 1, 0.36, 1) infinite",
        rise: "rise 0.5s cubic-bezier(0.22, 1, 0.36, 1) both",
        sweep: "sweep 1.6s cubic-bezier(0.22, 1, 0.36, 1) infinite",
      },
    },
  },
  plugins: [],
};
