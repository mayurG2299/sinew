// From assistant-ui's minimal template (MIT, @assistant-ui/react 0.15.23, templates/minimal/.../thread.aui.tsx).
// Changed: removed attachments, dictation, branch picker, message editing and the "more" menu (Sinew doesn't use
// them); the welcome text and composer placeholder come from props; assistant data parts named "sinew" render
// through `renderData` (actions, sources, the full picture).
import { MarkdownText } from "@/components/assistant-ui/markdown-text";
import { TooltipIconButton } from "@/components/assistant-ui/tooltip-icon-button";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  ActionBarPrimitive,
  AuiIf,
  type AssistantState,
  ComposerPrimitive,
  ErrorPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useAuiState,
} from "@assistant-ui/react";
import { ArrowDownIcon, ArrowUpIcon, CheckIcon, CopyIcon, SquareIcon } from "lucide-react";
import type { FC, ReactNode } from "react";

const isNewChatView = (s: AssistantState) =>
  s.thread.messages.length === 0 && (!s.thread.isLoading || s.threads.isLoading);

type Props = { welcome: ReactNode; placeholder: string; renderData: (name: string, data: any) => ReactNode };

export const Thread: FC<Props> = ({ welcome, placeholder, renderData }) => {
  const isEmpty = useAuiState(isNewChatView);

  return (
    <ThreadPrimitive.Root
      className="aui-root aui-thread-root bg-background @container flex h-full flex-col"
      style={{
        ["--thread-max-width" as string]: "44rem",
        ["--composer-bg" as string]: "color-mix(in oklab, var(--color-muted) 30%, transparent)",
        ["--composer-radius" as string]: "1rem",
        ["--composer-padding" as string]: "8px",
      }}
    >
      <ThreadPrimitive.Viewport
        turnAnchor="top"
        data-slot="aui_thread-viewport"
        className="relative flex flex-1 flex-col overflow-x-auto overflow-y-scroll scroll-smooth"
      >
        <div className={cn("mx-auto flex w-full max-w-(--thread-max-width) flex-1 flex-col px-4 pt-4", isEmpty && "justify-center")}>
          <AuiIf condition={isNewChatView}>
            <div className="aui-thread-welcome-root mb-6 flex flex-col px-2">{welcome}</div>
          </AuiIf>

          <div data-slot="aui_message-group" className="mb-14 flex flex-col gap-y-6 empty:hidden">
            <ThreadPrimitive.Messages>
              {() => <ThreadMessage renderData={renderData} />}
            </ThreadPrimitive.Messages>
          </div>

          <ThreadPrimitive.ViewportFooter
            className={cn(
              "aui-thread-viewport-footer bg-background flex flex-col gap-4 overflow-visible pb-4 md:pb-6",
              !isEmpty && "sticky bottom-0 mt-auto rounded-t-(--composer-radius)",
            )}
          >
            <ThreadScrollToBottom />
            <Composer placeholder={placeholder} />
          </ThreadPrimitive.ViewportFooter>
        </div>
      </ThreadPrimitive.Viewport>
    </ThreadPrimitive.Root>
  );
};

const ThreadMessage: FC<{ renderData: Props["renderData"] }> = ({ renderData }) => {
  const role = useAuiState((s) => s.message.role);
  if (role === "user") return <UserMessage />;
  return <AssistantMessage renderData={renderData} />;
};

const ThreadScrollToBottom: FC = () => (
  <ThreadPrimitive.ScrollToBottom asChild>
    <TooltipIconButton
      tooltip="Scroll to bottom"
      variant="outline"
      className="aui-thread-scroll-to-bottom absolute -top-12 z-10 self-center rounded-full p-4 disabled:invisible"
    >
      <ArrowDownIcon />
    </TooltipIconButton>
  </ThreadPrimitive.ScrollToBottom>
);

const Composer: FC<{ placeholder: string }> = ({ placeholder }) => (
  <ComposerPrimitive.Root className="aui-composer-root relative flex w-full flex-col">
    <div
      data-slot="aui_composer-shell"
      className="border-foreground/10 focus-within:border-foreground/25 flex w-full cursor-text flex-col gap-2 rounded-(--composer-radius) border bg-(--composer-bg) p-(--composer-padding) transition-[border-color]"
    >
      <ComposerPrimitive.Input
        placeholder={placeholder}
        className="aui-composer-input placeholder:text-muted-foreground/60 max-h-48 min-h-10 w-full resize-none bg-transparent px-2.5 py-1 text-base leading-6 outline-none"
        rows={1}
        autoFocus
        aria-label="Message input"
      />
      <div className="aui-composer-action-wrapper relative flex items-center justify-end">
        <AuiIf condition={(s) => !s.composer.canCancel}>
          <ComposerPrimitive.Send asChild>
            <TooltipIconButton tooltip="Send message" side="bottom" type="button" variant="default" size="icon"
              className="aui-composer-send size-7 rounded-full" aria-label="Send message">
              <ArrowUpIcon className="aui-composer-send-icon size-4" />
            </TooltipIconButton>
          </ComposerPrimitive.Send>
        </AuiIf>
        <AuiIf condition={(s) => s.composer.canCancel}>
          <ComposerPrimitive.Cancel asChild>
            <Button type="button" variant="default" size="icon" className="aui-composer-cancel size-7 rounded-full" aria-label="Stop generating">
              <SquareIcon className="aui-composer-cancel-icon size-3.5 fill-current" />
            </Button>
          </ComposerPrimitive.Cancel>
        </AuiIf>
      </div>
    </div>
  </ComposerPrimitive.Root>
);

const MessageError: FC = () => (
  <MessagePrimitive.Error>
    <ErrorPrimitive.Root className="aui-message-error-root border-destructive bg-destructive/10 text-destructive mt-2 rounded-md border p-3 text-sm">
      <ErrorPrimitive.Message className="aui-message-error-message line-clamp-2" />
    </ErrorPrimitive.Root>
  </MessagePrimitive.Error>
);

const AssistantMessage: FC<{ renderData: Props["renderData"] }> = ({ renderData }) => (
  <MessagePrimitive.Root
    data-slot="aui_assistant-message-root"
    data-role="assistant"
    className="fade-in slide-in-from-bottom-1 animate-in relative -mb-7.5 pb-7.5 duration-150"
  >
    <div data-slot="aui_assistant-message-content" className="text-foreground px-2 leading-relaxed wrap-break-word">
      <MessagePrimitive.Parts>
        {({ part }) => {
          if (part.type === "text") return <MarkdownText />;
          if (part.type === "data") return <>{renderData(part.name, part.data)}</>;
          return null;
        }}
      </MessagePrimitive.Parts>
      <AuiIf condition={(s) => s.message.status?.type === "running" && s.message.parts.length === 0}>
        <span data-slot="aui_assistant-message-indicator" className="text-muted-foreground animate-pulse text-sm" aria-label="Assistant is working">
          Looking through the company's data…
        </span>
      </AuiIf>
      <MessageError />
    </div>

    <div data-slot="aui_assistant-message-footer" className="ms-2 flex min-h-7.5 items-center pt-1.5">
      <ActionBarPrimitive.Root hideWhenRunning autohide="not-last"
        className="aui-assistant-action-bar-root text-muted-foreground animate-in fade-in -ms-1 flex gap-1 duration-200">
        <ActionBarPrimitive.Copy asChild>
          <TooltipIconButton tooltip="Copy">
            <AuiIf condition={(s) => s.message.isCopied}><CheckIcon /></AuiIf>
            <AuiIf condition={(s) => !s.message.isCopied}><CopyIcon /></AuiIf>
          </TooltipIconButton>
        </ActionBarPrimitive.Copy>
      </ActionBarPrimitive.Root>
    </div>
  </MessagePrimitive.Root>
);

const UserMessage: FC = () => (
  <MessagePrimitive.Root
    data-slot="aui_user-message-root"
    className="fade-in slide-in-from-bottom-1 animate-in grid auto-rows-auto grid-cols-[minmax(72px,1fr)_auto] content-start gap-y-2 px-2 duration-150 [&:where(>*)]:col-start-2"
    data-role="user"
  >
    <div className="aui-user-message-content-wrapper relative col-start-2 min-w-0">
      <div className="aui-user-message-content bg-muted text-foreground rounded-(--composer-radius) px-4 py-2 wrap-break-word empty:hidden">
        <MessagePrimitive.Parts />
      </div>
    </div>
  </MessagePrimitive.Root>
);
