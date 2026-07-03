// Two-letter initials for the header avatar chip. Splits on whitespace and
// takes the first letter of the first two words; for a single token, the first
// two characters; "?" when there is nothing usable.
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}
