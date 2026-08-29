import { FileText } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { AttachmentGrid } from "@/components/intake/attachment-grid";
import { CategoryPanel } from "@/components/intake/category-panel";
import { ReplyPanel } from "@/components/intake/reply-panel";
import { RequestMatchingPanel } from "@/components/transactions/request-matching-panel";
import { AiDisclaimer } from "@/components/shared/ai-disclaimer";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ApiError,
  fetchRequestDetail,
  fetchRequestReplies,
  type ReplyDraftList,
} from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";
import { STATUS_LABELS, canCorrect, labelFor } from "@/lib/intake";
import { normaliseRoles } from "@/lib/roles";
import { canWriteTransactions } from "@/lib/transactions";
import { formatDateTime } from "@/lib/utils";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Request" };

export default async function RequestDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  const { id } = await params;
  const roles = normaliseRoles(session.user.roles);

  let detail;
  try {
    detail = await fetchRequestDetail(session.accessToken, id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }

  // Read alongside the request rather than lazily from the panel: whether this deployment can
  // send at all is part of what the screen has to say honestly, and a panel that had to discover
  // it after mounting would offer a button before knowing whether it could work.
  let replies: ReplyDraftList | null = null;
  try {
    replies = await fetchRequestReplies(session.accessToken, id);
  } catch {
    // A failure here costs the reply panel and nothing else. The request itself still reads.
    replies = null;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={detail.request_code}
        description={detail.subject ?? "Uploaded through the portal, no email subject."}
        actions={
          <Button asChild variant="outline" size="sm">
            <Link href="/inbox">Back to inbox</Link>
          </Button>
        }
      />

      <AiDisclaimer />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle>Original message</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <dl className="grid gap-4 sm:grid-cols-2">
                <div>
                  <dt className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
                    From
                  </dt>
                  <dd className="mt-1 break-words text-sm text-foreground">
                    {detail.email
                      ? `${detail.email.sender_name ?? "Unknown sender"} · ${
                          detail.email.sender_address ?? "no address"
                        }`
                      : "Uploaded through the portal"}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
                    Received
                  </dt>
                  <dd className="mt-1 text-sm text-foreground">
                    {formatDateTime(detail.email?.received_at ?? detail.created_at)}
                  </dd>
                </div>
              </dl>

              {/* Rendered as text inside a pre element - sender-supplied content is never
                  interpreted as markup. */}
              <pre className="max-h-[28rem] overflow-auto whitespace-pre-wrap break-words rounded-md border border-border bg-surface p-4 font-sans text-sm leading-relaxed text-foreground">
                {detail.email?.body_text?.trim() ||
                  "This request carries no email body: it was created from a portal upload."}
              </pre>
            </CardContent>
          </Card>

          <section aria-labelledby="attachments-heading" className="space-y-3">
            <h2 id="attachments-heading" className="text-base font-semibold text-foreground">
              Attached documents ({detail.documents.length})
            </h2>
            {detail.documents.length > 0 ? (
              <AttachmentGrid documents={detail.documents} />
            ) : (
              <EmptyState
                icon={FileText}
                title="No documents on this request"
                description="Nothing was attached to the message, and nothing has been uploaded against it."
              />
            )}
          </section>
        </div>

        <div className="space-y-6">
          <CategoryPanel detail={detail} canCorrect={canCorrect(roles)} />

          <RequestMatchingPanel
            documents={detail.documents}
            canResolve={canWriteTransactions(roles)}
          />

          {replies ? (
            <ReplyPanel requestId={detail.id} replies={replies} canCompose={canCorrect(roles)} />
          ) : null}

          <Card>
            <CardHeader>
              <CardTitle>Request</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <Row label="Status">
                <Badge variant="muted">{labelFor(STATUS_LABELS, detail.status)}</Badge>
              </Row>
              <Row label="Source">
                <span className="capitalize text-foreground">{detail.source}</span>
              </Row>
              <Row label="Created">
                <span className="text-foreground">{formatDateTime(detail.created_at)}</span>
              </Row>
              <Row label="Last updated">
                <span className="text-foreground">{formatDateTime(detail.updated_at)}</span>
              </Row>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
        {label}
      </span>
      {children}
    </div>
  );
}
