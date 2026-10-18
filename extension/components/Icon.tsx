const paths = {
  arrow: "M12 19V5m-6 6 6-6 6 6",
  attach: "m8 13 6-6a3 3 0 0 1 4 4l-8 8a5 5 0 0 1-7-7l9-9",
  at: "M16 8v6a2 2 0 0 0 4 0v-2a8 8 0 1 0-3 6M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0",
  check: "m5 12 4 4L19 6",
  chevron: "m9 5 7 7-7 7",
  close: "m6 6 12 12M6 18 18 6",
  code: "m8 7-5 5 5 5m8-10 5 5-5 5m-3-14-2 18",
  file: "M14 3H5v18h14V8l-5-5v5h5M8 13h8m-8 4h5",
  globe:
    "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0M3 12h18M12 3a18 18 0 0 1 0 18 18 18 0 0 1 0-18",
  link: "m10 13 4-4M8 16l-1 1a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0m2 1 1-1a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0",
  pause: "M8 5v14M16 5v14",
  play: "m8 4 12 8-12 8V4Z",
  settings: "M4 7h16M4 17h16M8 4v6m8 4v6",
  slash: "m15 4-6 16",
  stop: "M6 6h12v12H6Z",
  tab: "M3 5h18v15H3V5Zm0 4h18M7 7h.01",
  thought: "M8 18h8m-7 3h6M8 15a7 7 0 1 1 8 0v3H8v-3Z",
} as const;

export type IconName = keyof typeof paths;

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}
