import { Database } from "lucide-react";
import { StatusBadge } from "./StatusBadge";

interface MockDataBadgeProps {
  label?: string;
  className?: string;
}

export function MockDataBadge({
  label = "Mock data",
  className,
}: MockDataBadgeProps) {
  return (
    <StatusBadge
      variant="warning"
      icon={<Database className="h-3 w-3" />}
      className={className}
    >
      {label}
    </StatusBadge>
  );
}
