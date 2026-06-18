import type { ReactNode } from "react";

interface AuroraBackgroundProps {
  children: ReactNode;
}

export function AuroraBackground({ children }: AuroraBackgroundProps) {
  return (
    <>
      <div className="aurora-bg grain fixed inset-0 -z-10" aria-hidden="true" />
      <div className="relative z-10 min-h-screen">{children}</div>
    </>
  );
}
