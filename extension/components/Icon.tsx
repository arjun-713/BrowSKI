const paths = {
  brand: "M6 4h7a4 4 0 0 1 0 8H6m0 0h8a4 4 0 0 1 0 8H6V4m4 0v16",
  plus: "M12 5v14M5 12h14",
  history: "M3 5v5h5M4 9a8 8 0 1 1 0 6m8-8v5l3 2",
  refresh: "M20 7v5h-5M4 17v-5h5m-4-4a8 8 0 0 1 13-3l2 3M4 16l2 3a8 8 0 0 0 13-3",
  copy: "M9 9h11v12H9V9ZM5 15H3V3h11v2",
  checkCircle: "M21 11v1a9 9 0 1 1-5-8M8 11l4 4L22 5",
  info: "M12 11v6m0-10h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
  connection: "M8 3v5m8-5v5M6 8h12v3a6 6 0 0 1-12 0V8Zm6 9v4",
  key: "M14 6a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM10 10v11m0-4h4m-4-4h3",
  diagonal: "M6 18 18 6M6 6h12v12",
  read: "M4 4h6a2 2 0 0 1 2 2v15a3 3 0 0 0-3-2H4V4Zm16 0h-6a2 2 0 0 0-2 2v15a3 3 0 0 1 3-2h5V4Z",
  type: "M4 5h16M12 5v14m-4 0h8",
  click: "m5 3 4 17 3-6 6-3L5 3Zm8 11 5 6",
  scroll: "M12 3v18m-4-4 4 4 4-4M8 7l4-4 4 4",
  wait: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0M12 7v5l3 2",
  back: "M19 12H5m6-6-6 6 6 6",
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
  settings:
    "M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1 1-3Zm6 9a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
  search: "M20 20l-4.3-4.3M17 10.5a6.5 6.5 0 1 1-13 0 6.5 6.5 0 0 1 13 0",
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
