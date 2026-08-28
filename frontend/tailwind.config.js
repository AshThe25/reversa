/**
 * Neo-brutalism.
 *
 * The constraint that defines the system: shadows have no blur. A hard offset
 * black shadow reads as a physical object sitting on a surface, and the moment
 * you add a blur radius it turns into an ordinary drop shadow and the whole
 * language collapses. Same with radii — sharp by default, and only the few
 * places the system explicitly allows get rounded.
 *
 * Cabinet Grotesk and Satoshi are the specified faces. Both are Fontshare
 * releases with no npm package, and the app's CSP forbids remote font hosts, so
 * they are substituted with the closest self-hostable equivalents: Space
 * Grotesk for display (same geometric grotesk with the distinctive tall
 * lowercase) and Manrope for body. Loosening the CSP to pull fonts off a CDN
 * would be trading a real security property for a typographic near-match.
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        cyber: { DEFAULT: "#f5d949", deep: "#e6c62f", wash: "#fdf3c4" },
        // Sampled off the hero plate so the flat area of the section and the
        // image meet without a seam. Do not "correct" this to `cyber`.
        plate: "#fdd860",
        // Razorpay's blue as the secondary accent. One saturated support colour
        // against the yellow is the whole palette; a third would turn the
        // illustration into a paint chart.
        rzp: { DEFAULT: "#2b7fff", deep: "#1a5fd0" },
        navy: "#0f1b3d",
        cream: "#fbf7e8",
        charcoal: "#171e19",
        sage: "#b7c6c2",
        graphite: "#272727",
        paper: "#f4f4f5",
        signal: {
          loss: "#e5484d",
          // The same red fails AA as text - 3.9:1 on the tinted card it usually
          // sits on. `loss` stays the fill; `loss-ink` is the one you write in.
          "loss-ink": "#b3252a",
          natural: "#8b8b8b",
          incremental: "#ffe17c",
          calm: "#30a46c",
          info: "#5b8def",
        },
      },
      fontFamily: {
        display: ["Space Grotesk Variable", "Space Grotesk", "system-ui", "sans-serif"],
        sans: ["Manrope Variable", "Manrope", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      letterSpacing: {
        tighter: "-0.05em",
        label: "0.14em",
      },
      boxShadow: {
        // No blur, ever. That is the entire language.
        "hard-sm": "4px 4px 0px 0px #000000",
        hard: "6px 6px 0px 0px #000000",
        "hard-md": "8px 8px 0px 0px #000000",
        "hard-lg": "12px 12px 0px 0px #000000",
        "hard-yellow": "6px 6px 0px 0px #ffe17c",
        "hard-inset": "inset 4px 4px 0px 0px #000000",
      },
      borderRadius: { neo: "2px", btn: "12px", card: "2px" },
      transitionTimingFunction: { neo: "cubic-bezier(0.175, 0.885, 0.32, 1.275)" },
      backgroundImage: {
        dots: "radial-gradient(#000000 1.5px, transparent 1.5px)",
      },
      backgroundSize: { dots: "32px 32px" },
      keyframes: {
        marquee: { from: { transform: "translateX(0)" }, to: { transform: "translateX(-50%)" } },
        rise: {
          from: { opacity: "0", transform: "translateY(12px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        sweep: { from: { transform: "translateX(-100%)" }, to: { transform: "translateX(200%)" } },
      },
      animation: {
        marquee: "marquee 30s linear infinite",
        rise: "rise 0.35s cubic-bezier(0.175, 0.885, 0.32, 1.275) both",
        sweep: "sweep 1.4s linear infinite",
      },
    },
  },
  plugins: [],
};
