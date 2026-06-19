// Editor icons, mapped to lucide-react. Keyed by tool/action name so callers
// just do <Icon name="rect" />. lucide icons stroke with currentColor, so they
// inherit each button's hover/active colour.
import {
  ArrowDownAZ,
  Circle,
  DoorClosed,
  GripHorizontal,
  Hexagon,
  MousePointer2,
  Sparkles,
  Spline,
  Square,
  Type,
  Waves,
  Waypoints,
  type LucideIcon,
} from "lucide-react";

const ICONS: Record<string, LucideIcon> = {
  select: MousePointer2,
  rect: Square,
  circle: Circle,
  polygon: Hexagon,
  cave: Spline,
  corridor: Waypoints,
  door: DoorClosed,
  feature: Sparkles,
  text: Type,
  area: Waves,
  line: GripHorizontal,
  sort: ArrowDownAZ,
};

export function Icon({ name, size = 18 }: { name: string; size?: number }) {
  const Cmp = ICONS[name];
  if (!Cmp) return null;
  return <Cmp size={size} strokeWidth={2} aria-hidden />;
}
