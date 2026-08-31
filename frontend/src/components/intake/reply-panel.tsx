"use client";

import { Mail, Send } from "lucide-react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useState } from "react";
import toast from "react-hot-toast";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  ApiError,
  composeRequestReply,
  sendRequestReply,
  withdrawRequestReply,
  type ReplyDraftList,
} from "@/lib/api-client";
import { formatDateTime } from "@/lib/utils";

export interface ReplyPanelProps {
  requestId: string;
  replies: ReplyDraftList;
  canCompose: boolean;
}

const MIN_MESSAGE = 20;

const STATUS_LABELS: Record<string, string> = {
  draft: "Drafted, not sent",
  sent: "Sent",
  failed: "Send failed",
  withdrawn: "Withdrawn",
};

/**
 * Answering the broker or supplier on the thread their message arrived on.
 *
 * Two buttons, never one, and that is the whole design. Composing writes a draft and reaches no
 * mailbox; sending is a second, deliberate act recorded against the account that made it. The
 * platform has no path that does both, and this panel is the only place in the application from
 * which a message leaves for a counterparty at all.
 *
 * The standing disclaimer and the reference are appended by the server, not by this form, so a
 * reply cannot be sent without them and the desk can read exactly what will go out before it does.
 */
export function ReplyPanel({ requestId, replies, canCompose }: ReplyPanelProps) {
  const router = useRouter();
  const { data: session } = useSession();
  const [message, setMessage] = useState("");
  const [working, setWorking] = useState<string | null>(null);

  const token = session?.accessToken;
  const ready = message.trim().length >= MIN_MESSAGE;

  async function run(key: string, action: () => Promise<unknown>, success: string) {
    if (!token) {
      toast.error("Your session has expired. Sign in again.");
      return;
    }
    setWorking(key);
    try {
      await action();
      toast.success(success);
      router.refresh();
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "That could not be completed.");
    } finally {
      setWorking(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Mail className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          Reply on this thread
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm leading-relaxed text-muted-foreground">
          {replies.recipient_address
            ? `A reply goes back to ${replies.recipient_address} on the original conversation, so their answer lands on this same request.`
            : "This request came from a portal upload, so there is no thread to reply on."}
        </p>

        {replies.recipient_address && !replies.outbound_enabled ? (
          <p
            role="note"
            className="rounded-medium border-thin border-pill-amber-border bg-pill-amber-bg px-space-150 py-space-100 text-body-sm leading-relaxed text-foreground"
          >
            Sending from the shared mailbox is not enabled on this deployment. A reply can still be
            drafted and read here; it cannot leave until AGFZE IT grants the mailbox send
            permission and the platform is switched on for it.
          </p>
        ) : null}

        {replies.items.length > 0 ? (
          <ul className="space-y-3">
            {replies.items.map((draft) => (
              <li key={draft.id} className="rounded-medium border-thin border-border bg-elevation-sunken p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Badge variant={draft.status === "sent" ? "secondary" : "muted"}>
                    {STATUS_LABELS[draft.status] ?? draft.status}
                  </Badge>
                  <span className="text-xs text-muted-foreground">
                    {draft.status === "sent" && draft.sent_at
                      ? `${draft.sent_by_name ?? "Sent"} · ${formatDateTime(draft.sent_at)}`
                      : `${draft.composed_by_name ?? "Drafted"} · ${formatDateTime(draft.composed_at)}`}
                  </span>
                </div>

                {/* Rendered as text. What was composed is what is shown, and it is never markup. */}
                <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-foreground">
                  {draft.body_text}
                </pre>

                {draft.failure_reason ? (
                  <p className="mt-2 text-xs text-signal-blocked">
                    The mailbox refused it: {draft.failure_reason}. Nothing was delivered.
                  </p>
                ) : null}

                {canCompose && draft.status !== "sent" && draft.status !== "withdrawn" ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      disabled={working !== null || !replies.outbound_enabled}
                      onClick={() =>
                        run(
                          draft.id,
                          () => sendRequestReply(token!, requestId, draft.id),
                          "Sent on the original thread, recorded against your account.",
                        )
                      }
                    >
                      <Send className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
                      {working === draft.id ? "Sending…" : "Send this reply"}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={working !== null}
                      onClick={() =>
                        run(
                          `${draft.id}-withdraw`,
                          () => withdrawRequestReply(token!, requestId, draft.id),
                          "Withdrawn. Nothing was sent.",
                        )
                      }
                    >
                      Withdraw
                    </Button>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}

        {canCompose && replies.recipient_address ? (
          <div className="space-y-1.5">
            <Label htmlFor="reply-message">What should the desk say?</Label>
            <Textarea
              id="reply-message"
              rows={5}
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              placeholder="Confirming 125 MT copper against your reference. Contract to follow today."
              aria-describedby="reply-message-help"
            />
            <p id="reply-message-help" className="text-xs text-muted-foreground">
              At least {MIN_MESSAGE} characters. The request reference and the standing disclaimer
              are added by the platform, so you will see exactly what goes out before it does -
              drafting sends nothing.
            </p>
            <Button
              size="sm"
              disabled={!ready || working !== null}
              onClick={() =>
                run(
                  "compose",
                  async () => {
                    await composeRequestReply(token!, requestId, { message: message.trim() });
                    setMessage("");
                  },
                  "Drafted. Read it back and send it deliberately.",
                )
              }
            >
              {working === "compose" ? "Drafting…" : "Draft a reply"}
            </Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
