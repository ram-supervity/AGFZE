"use client";

import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useState } from "react";
import toast from "react-hot-toast";

import { PushSettings } from "@/components/pwa/push-settings";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { ApiError, updateMyPreferences, type UserProfile } from "@/lib/api-client";
import { channelForEmail, emailIsEnabled } from "@/lib/notifications";
import { ROLE_DESCRIPTIONS, ROLE_LABELS, normaliseRoles } from "@/lib/roles";
import { formatDateTime } from "@/lib/utils";

export interface SettingsFormProps {
  profile: UserProfile;
}

const STREAM_OPTIONS = [
  { value: "", label: "No preference" },
  { value: "scrap", label: "Scrap trading" },
  { value: "fa", label: "FA" },
] as const;

/**
 * The signed-in account's own settings, and only their own.
 *
 * The profile block is read-only because the identity provider owns every value in it. Name,
 * email and roles arrive with the token on each sign-in and are overwritten from it, so an
 * editable field here would be a control that silently undoes itself.
 *
 * The delivery section is deliberately not three radio buttons. The three channels are not
 * alternatives to one another and never were:
 *
 *   in-app  always on, for everybody. It is stated and not offered, because it is the platform's
 *           record of having told somebody something rather than a choice.
 *   email   a simple toggle, and the only thing `notification_channel` actually governs.
 *   push    a browser permission for this device, with its own control — a different kind of
 *           thing entirely from a database preference, and presented as one.
 */
export function SettingsForm({ profile }: SettingsFormProps) {
  const router = useRouter();
  const { data: session } = useSession();
  const [emailCopies, setEmailCopies] = useState(emailIsEnabled(profile.notification_channel));
  const [stream, setStream] = useState(profile.default_stream_filter ?? "");
  const [saving, setSaving] = useState(false);

  const roles = normaliseRoles(profile.roles);
  const channel = channelForEmail(emailCopies);
  const changed =
    emailCopies !== emailIsEnabled(profile.notification_channel) ||
    stream !== (profile.default_stream_filter ?? "");

  async function save() {
    const token = session?.accessToken;
    if (!token) {
      toast.error("Your session has expired. Sign in again to save your preferences.");
      return;
    }
    setSaving(true);
    try {
      await updateMyPreferences(token, {
        notification_channel: channel,
        default_stream_filter: stream || null,
      });
      toast.success("Your preferences are saved.");
      router.refresh();
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "Your preferences could not be saved.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <section className="space-y-3 rounded-lg border border-border bg-surface p-4">
        <div>
          <h2 className="text-sm font-semibold text-foreground">Profile</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Mirrored from the identity provider and refreshed on every sign-in. It is read-only
            here because Entra ID owns it — a change made on this page would be overwritten by
            your next token.
          </p>
        </div>

        <dl className="grid gap-4 sm:grid-cols-2">
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">Name</dt>
            <dd className="mt-0.5 text-sm text-foreground">{profile.display_name}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">Email</dt>
            <dd className="mt-0.5 text-sm text-foreground">{profile.email}</dd>
          </div>
          <div className="sm:col-span-2">
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">Roles</dt>
            <dd className="mt-1 flex flex-wrap gap-1.5">
              {roles.map((role) => (
                <Badge key={role} variant="muted" title={ROLE_DESCRIPTIONS[role]}>
                  {ROLE_LABELS[role]}
                </Badge>
              ))}
            </dd>
            <p className="mt-1.5 text-xs text-muted-foreground">
              Roles are mapped from your Entra ID groups. An administrator can override them, and
              the change reaches you on your next sign-in.
            </p>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">
              Account created
            </dt>
            <dd className="mt-0.5 text-sm text-foreground">
              {formatDateTime(profile.created_at)}
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">
              Last sign-in
            </dt>
            <dd className="mt-0.5 text-sm text-foreground">
              {formatDateTime(profile.last_login_at) ?? "This session"}
            </dd>
          </div>
        </dl>
      </section>

      <section className="space-y-4 rounded-lg border border-border bg-surface p-4">
        <div>
          <h2 className="text-sm font-semibold text-foreground">Preferences</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            How the platform reaches you when an exception lands on your desk, a decision is
            waiting on you, or something you submitted comes back. The three channels below are
            independent — you can be on all of them at once.
          </p>
        </div>

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium text-foreground">Delivery</legend>

          <div className="rounded-md border border-dashed border-border px-3 py-2.5">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-foreground">In-app</span>
              <Badge variant="muted">Always on</Badge>
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Every notification is written to your notification centre and counted by the bell in
              the header. It is the platform&rsquo;s record of having told you, so it is not a
              setting and cannot be switched off.
            </p>
          </div>

          <label className="flex items-start gap-2.5 rounded-md border border-border px-3 py-2.5 text-sm">
            <input
              type="checkbox"
              name="email-copies"
              className="mt-0.5 h-4 w-4"
              checked={emailCopies}
              onChange={(event) => setEmailCopies(event.target.checked)}
            />
            <span className="min-w-0">
              <span className="font-medium text-foreground">Email</span>
              <span className="mt-0.5 block text-xs text-muted-foreground">
                Send a copy of every notification to {profile.email}, with a link into the screen
                it is about. Saved with the button below.
              </span>
            </span>
          </label>

          {/* Push is not a fourth line in this list, and not a checkbox: enabling it is a real
              browser permission interaction on this specific device, which no preference here can
              grant, revoke or speak for. */}
          <PushSettings />
        </fieldset>

        <div className="space-y-1.5">
          <Label htmlFor="stream-preference">Preferred business stream</Label>
          <Select
            id="stream-preference"
            value={stream}
            onChange={(event) => setStream(event.target.value)}
          >
            {STREAM_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
          <p className="text-xs text-muted-foreground">
            Recorded against your account. No screen reads it yet, so setting it changes nothing
            you see today — it is said here rather than left to be discovered. Whatever it is set
            to, your queues and dashboard stay scoped by your roles and never by this.
          </p>
        </div>

        <div className="flex justify-end">
          <Button onClick={save} disabled={!changed || saving}>
            {saving ? "Saving…" : "Save preferences"}
          </Button>
        </div>
      </section>
    </div>
  );
}
