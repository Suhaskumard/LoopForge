import type { ReactNode } from "react";

/** Tiny inline icon set (no dependency). All are decorative: aria-hidden. */
const base = { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true } as const;
const icon = (d: ReactNode) => () => <svg {...base}>{d}</svg>;

export const IconHome = icon(<><path d="M3 11l9-8 9 8" /><path d="M5 10v10h14V10" /></>);
export const IconPlus = icon(<><circle cx="12" cy="12" r="9" /><path d="M12 8v8M8 12h8" /></>);
export const IconChart = icon(<><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></>);
export const IconShield = icon(<><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" /></>);
export const IconSun = icon(<><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M5 19l1.5-1.5M17.5 6.5L19 5" /></>);
export const IconGear = icon(<><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z" /></>);
export const IconFlow = icon(<><circle cx="5" cy="12" r="2.5" /><circle cx="19" cy="6" r="2.5" /><circle cx="19" cy="18" r="2.5" /><path d="M7.5 12h4l5-5M11.5 12l5 5" /></>);
export const IconCode = icon(<><path d="M8 8l-5 4 5 4M16 8l5 4-5 4M14 5l-4 14" /></>);
export const IconCheck = icon(<><circle cx="12" cy="12" r="9" /><path d="M8 12l3 3 5-6" /></>);
export const IconDoc = icon(<><path d="M6 3h8l4 4v14H6z" /><path d="M14 3v4h4M9 12h6M9 16h6" /></>);
export const IconRocket = icon(<><path d="M5 15c-1.5 1.5-2 5-2 5s3.5-.5 5-2" /><path d="M9 15l-3-3c2-6 7-9 14-9 0 7-3 12-9 14z" /><circle cx="15" cy="9" r="1.6" /></>);
export const IconGraph = icon(<><circle cx="6" cy="6" r="2.5" /><circle cx="18" cy="7" r="2.5" /><circle cx="12" cy="18" r="2.5" /><circle cx="19" cy="17" r="1.6" /><path d="M8.3 6.4l7.4.4M7.2 8.2l3.7 7.6M16.9 9.2l-3.8 6.8M14.4 18l3-.6" /></>);
export const IconBulb = icon(<><path d="M9 18h6M10 21h4" /><path d="M12 3a6 6 0 00-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0012 3z" /></>);
export const IconEye = icon(<><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></>);
export const IconEyeOff = icon(<><path d="M3 3l18 18" /><path d="M10.6 5.1A9.6 9.6 0 0112 5c6 0 10 7 10 7a17 17 0 01-3.2 3.9M6.6 6.6C3.8 8.4 2 12 2 12s4 7 10 7c1.6 0 3-.4 4.3-1" /><path d="M9.9 9.9a3 3 0 004.2 4.2" /></>);
export const IconMoon = icon(<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z" />);

export function Logo() {
  return (
    <svg className="logo" viewBox="0 0 32 32" aria-hidden="true">
      <defs>
        <linearGradient id="lf-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#8b7bff" />
          <stop offset="1" stopColor="#38d5f5" />
        </linearGradient>
      </defs>
      <g className="spin">
        <path d="M16 4a12 12 0 1 1-11.4 8.3" fill="none" stroke="url(#lf-g)" strokeWidth="3" strokeLinecap="round" />
        <path d="M2 8.5l3.2 4.4 4.2-3.3" fill="none" stroke="url(#lf-g)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      </g>
      <circle cx="16" cy="16" r="3.4" fill="url(#lf-g)" />
    </svg>
  );
}
