// From assistant-ui's minimal template (MIT). Changed: the hover hint uses the native title attribute
// instead of a tooltip library.
import { type ComponentPropsWithRef, forwardRef } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type TooltipIconButtonProps = ComponentPropsWithRef<typeof Button> & {
  tooltip: string;
  side?: "top" | "bottom" | "left" | "right";
};

export const TooltipIconButton = forwardRef<HTMLButtonElement, TooltipIconButtonProps>(
  ({ children, tooltip, side: _side, className, ...rest }, ref) => (
    <Button variant="ghost" size="icon" title={tooltip} {...rest}
      className={cn("aui-button-icon size-6 p-1 active:scale-90", className)} ref={ref}>
      {children}
      <span className="aui-sr-only sr-only">{tooltip}</span>
    </Button>
  ),
);

TooltipIconButton.displayName = "TooltipIconButton";
