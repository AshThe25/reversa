/**
 * Hero illustration.
 *
 * Inline SVG rather than an asset: the app's CSP blocks remote images, and an
 * inline mark inherits the palette tokens so a colour change does not require
 * re-exporting artwork.
 *
 * Deliberately NOT the Razorpay logomark. The reference composition leans on
 * their ascending chevron, and reproducing a company's trademark inside a
 * submission to that company is a bad idea however flattering the intent. This
 * is an abstract ascending arrow in the same isometric language — same
 * geometry, same weight, not their asset.
 *
 * Halftone shading is a real SVG pattern rather than a raster: it scales, it
 * stays crisp, and it costs about forty bytes.
 */
export function HeroArt({ className = "" }: { className?: string }) {
  return (
    <svg
      viewBox="235 120 600 620"
      className={className}
      role="img"
      aria-label="An ascending arrow rising over a bar chart of payment volume"
    >
      <defs>
        <pattern id="halftone" width="8" height="8" patternUnits="userSpaceOnUse">
          <circle cx="2" cy="2" r="1.6" fill="#0f1b3d" opacity="0.55" />
        </pattern>
        <pattern id="halftone-light" width="9" height="9" patternUnits="userSpaceOnUse">
          <circle cx="2" cy="2" r="1.4" fill="#0f1b3d" opacity="0.28" />
        </pattern>
        <clipPath id="clip-tower-a">
          <path d="M596 470 L664 452 L664 700 L596 700 Z" />
        </clipPath>
        <clipPath id="clip-tower-b">
          <path d="M676 432 L752 410 L752 700 L676 700 Z" />
        </clipPath>
      </defs>

      {/* ------------------------------------------------ the ascending mark */}
      {/* navy slab sitting behind the arrow, catching its shadow */}
      <path
        d="M300 640 L470 250 L610 250 L440 640 Z"
        fill="#0f1b3d"
        stroke="#000"
        strokeWidth="3"
      />

      {/* cream separator, so the blue reads as lifted off the navy */}
      <path d="M452 640 L622 250 L648 250 L478 640 Z" fill="#fbf7e8" stroke="#000" strokeWidth="3" />

      {/* the arrow itself */}
      <path
        d="M470 640 L638 254 L598 186 L744 150 L742 300 L698 236 L522 640 Z"
        fill="#2b7fff"
        stroke="#000"
        strokeWidth="3"
        strokeLinejoin="round"
      />
      {/* halftone falloff on the arrow's shaded face */}
      <path d="M470 640 L638 254 L662 300 L522 640 Z" fill="url(#halftone)" opacity="0.32" />

      {/* --------------------------------------------------- volume towers */}
      <g stroke="#000" strokeWidth="3">
        <path d="M520 560 L568 546 L568 700 L520 700 Z" fill="#f5d949" />
        <path d="M596 470 L664 452 L664 700 L596 700 Z" fill="#f5d949" />
        <g clipPath="url(#clip-tower-a)">
          <rect x="596" y="452" width="68" height="120" fill="url(#halftone-light)" />
        </g>
        <path d="M676 432 L752 410 L752 700 L676 700 Z" fill="#0f1b3d" />
        <g clipPath="url(#clip-tower-b)">
          <rect x="676" y="410" width="76" height="150" fill="url(#halftone)" opacity="0.5" />
        </g>
        <path d="M764 496 L812 482 L812 700 L764 700 Z" fill="#f5d949" />
      </g>

      {/* ground plane */}
      <path d="M240 700 L820 626 L820 720 L240 720 Z" fill="#0f1b3d" stroke="#000" strokeWidth="3" />
      <path d="M300 690 L820 624" stroke="#2b7fff" strokeWidth="3" fill="none" />

      {/* ------------------------------------------------------- the orbit */}
      <ellipse
        cx="530"
        cy="470"
        rx="300"
        ry="150"
        fill="none"
        stroke="#0f1b3d"
        strokeWidth="2.5"
        strokeDasharray="8 10"
        transform="rotate(-18 530 470)"
      />
      <circle cx="272" cy="392" r="8" fill="#2b7fff" stroke="#000" strokeWidth="2.5" />
      <circle cx="300" cy="588" r="8" fill="#2b7fff" stroke="#000" strokeWidth="2.5" />
      <circle cx="782" cy="186" r="9" fill="#2b7fff" stroke="#000" strokeWidth="2.5" />
      <circle cx="812" cy="228" r="8" fill="#fff" stroke="#000" strokeWidth="2.5" />
      <circle cx="256" cy="470" r="3.5" fill="#0f1b3d" />

      {/* ------------------------------------------------- floating tiles */}
      <IconTile x={676} y={214} icon="bolt" />
      <IconTile x={296} y={452} icon="code" />
      <IconTile x={708} y={520} icon="shield" />

      {/* Texture belongs at the frame edge or not at all - at the old viewBox
          these sat mid-composition and read as debris. */}
      <rect x="235" y="640" width="120" height="100" fill="url(#halftone-light)" opacity="0.6" />
    </svg>
  );
}

const PATHS: Record<string, string> = {
  bolt: "M13 2 L5 13 h5 l-1 9 8-12 h-5 z",
  code: "M9 7 L4 12 l5 5 M15 7 l5 5 -5 5",
  shield: "M12 3 l8 3 v6 c0 4.5-3.3 8.3-8 9.5C7.3 20.3 4 16.5 4 12V6z M9 12 l2.2 2.4L15.5 10",
};

/** A rounded tile with a hard offset shadow — the 2D language, in the artwork. */
function IconTile({ x, y, icon }: { x: number; y: number; icon: keyof typeof PATHS | string }) {
  const size = 78;
  return (
    <g transform={`translate(${x} ${y})`}>
      <rect x="7" y="7" width={size} height={size} rx="12" fill="url(#halftone)" opacity="0.6" />
      <rect
        x="0"
        y="0"
        width={size}
        height={size}
        rx="12"
        fill="#f5d949"
        stroke="#000"
        strokeWidth="3"
      />
      <g transform={`translate(${size / 2 - 13} ${size / 2 - 13}) scale(1.08)`}>
        <path
          d={PATHS[icon] ?? PATHS.bolt}
          fill={icon === "code" ? "none" : "#0f1b3d"}
          stroke="#0f1b3d"
          strokeWidth={icon === "code" ? 2.6 : 1.6}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </g>
    </g>
  );
}
