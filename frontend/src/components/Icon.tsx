// Inline SVG icons from demo-static-mvp/app/js/icons.js (24px grid, stroke=currentColor).
const PATHS: Record<string, string> = {
  ask: '<path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 8.5 8.5 0 0 1-3.8-.9L3 21l1.9-5.7A8.5 8.5 0 1 1 21 11.5z"/><path d="M8.5 11h7M8.5 14h4"/>',
  conversations:
    '<path d="M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><path d="M8 9h8M8 13h5"/>',
  collapse: '<path d="M15 6l-6 6 6 6"/>',
  chevronRight: '<path d="M9 6l6 6-6 6"/>',
  chevronDown: '<path d="M6 9l6 6 6-6"/>',
  send: '<path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4z"/>',
  sparkles:
    '<path d="M12 3l1.6 4.4L18 9l-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
  eligibility:
    '<circle cx="9" cy="8" r="3.2"/><path d="M3.5 20a5.5 5.5 0 0 1 11 0"/><path d="M17 11l2 2 3.5-3.5"/>',
  spending:
    '<circle cx="12" cy="12" r="9"/><path d="M12 7v10M14.5 9.3c-.5-1-1.5-1.4-2.7-1.4-1.5 0-2.6.8-2.6 2 0 2.8 5.4 1.6 5.4 4.4 0 1.2-1.1 2-2.8 2-1.3 0-2.4-.5-2.9-1.5"/>',
  er: '<path d="M22 12h-4l-3 7-6-14-3 7H2"/>',
  cohort: '<circle cx="9" cy="12" r="5"/><circle cx="15" cy="12" r="5"/>',
  download:
    '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
  check: '<polyline points="20 6 9 17 4 12"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.5v.01"/>',
  warn: '<path d="M10.3 3.3L2 18a2 2 0 0 0 1.7 3h16.6A2 2 0 0 0 22 18L13.7 3.3a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17v.01"/>',
  arrowRight: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  methodology:
    '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
  provenance: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/>',
};

export function Icon({ name }: { name: keyof typeof PATHS }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: PATHS[name] }}
    />
  );
}
