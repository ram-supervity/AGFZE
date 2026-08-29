"use client";

import { ArrowDown, ArrowUp, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { ChangeReasonField } from "@/components/admin/change-reason-field";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  headlineFigureLabel,
  reasonIsValid,
  reportTypeLabel,
  sectionKindLabel,
  sectionSourceLabel,
} from "@/lib/admin";
import type {
  ReportTemplateBody,
  ReportTemplateList,
  ReportTemplateRow,
  ReportTemplateSection,
} from "@/lib/api-client";

export interface ReportTemplateDialogProps {
  row: ReportTemplateRow | null;
  vocabularies: Pick<ReportTemplateList, "section_kinds" | "section_sources" | "headline_figures">;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  saving: boolean;
  onSave: (body: ReportTemplateBody) => Promise<void>;
}

const HEADLINE_SOURCE = "headline";
const KPI_GRID = "kpi_grid";

/**
 * Edit what one report is made of.
 *
 * Everything on this form decides what is *asked for*. Nothing on it decides what the answer is:
 * a section names a data block the reporting service already produces, and the block's figures
 * are computed from the governed tables when the report runs. That is why there is no field here
 * for a value, a threshold or a target anywhere - there could not be one.
 *
 * The report type and the template key are shown and are not editable. They are the row's
 * identity: every generated report records which template produced it, so re-pointing one would
 * leave those records claiming a structure the document was never built to. The API's update
 * schema has no field for either, so this is not a UI-only restriction.
 */
export function ReportTemplateDialog({
  row,
  vocabularies,
  open,
  onOpenChange,
  saving,
  onSave,
}: ReportTemplateDialogProps) {
  const [title, setTitle] = useState("");
  const [sections, setSections] = useState<ReportTemplateSection[]>([]);
  const [reason, setReason] = useState("");

  useEffect(() => {
    if (!row) return;
    setTitle(row.title);
    setSections(row.sections.map((section) => ({ ...section, figures: [...section.figures] })));
    setReason("");
  }, [row]);

  if (!row) return null;

  function move(index: number, delta: number) {
    setSections((current) => {
      const target = index + delta;
      if (target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  function remove(index: number) {
    setSections((current) => current.filter((_, position) => position !== index));
  }

  function update(index: number, changes: Partial<ReportTemplateSection>) {
    setSections((current) =>
      current.map((section, position) =>
        position === index ? { ...section, ...changes } : section,
      ),
    );
  }

  function toggleFigure(index: number, figure: string) {
    setSections((current) =>
      current.map((section, position) => {
        if (position !== index) return section;
        const chosen = section.figures.includes(figure)
          ? section.figures.filter((value) => value !== figure)
          : [...section.figures, figure];
        return { ...section, figures: chosen };
      }),
    );
  }

  const original = JSON.stringify({ title: row.title, sections: row.sections });
  const proposed = JSON.stringify({ title, sections });
  const changed = original !== proposed;
  const ready = changed && sections.length > 0 && title.trim() !== "" && reasonIsValid(reason);

  async function submit() {
    if (!ready) return;
    await onSave({ change_reason: reason.trim(), title: title.trim(), sections });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <div className="space-y-1.5">
          <DialogTitle>{reportTypeLabel(row.report_type)} report</DialogTitle>
          <DialogDescription>
            {row.description} This decides what the report asks for. Every figure in it is
            computed from the governed tables when the report is generated.
          </DialogDescription>
        </div>

        <dl className="grid grid-cols-2 gap-3 rounded-md border border-border bg-surface px-3 py-2.5 text-sm">
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">Template key</dt>
            <dd className="font-mono text-foreground">{row.template_key}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">Report type</dt>
            <dd className="text-foreground">{reportTypeLabel(row.report_type)}</dd>
          </div>
        </dl>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="template-title">Title on the document</Label>
            <Input
              id="template-title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              aria-invalid={title.trim() === "" || undefined}
            />
          </div>

          <div className="space-y-3">
            <h3 className="text-sm font-semibold text-foreground">
              Sections, in the order they are printed
            </h3>

            {sections.length === 0 ? (
              <p role="alert" className="text-xs text-signal-blocked">
                A report has to carry at least one section. Put one back before saving.
              </p>
            ) : null}

            <ol className="space-y-3">
              {sections.map((section, index) => (
                <li
                  key={`${section.key}-${index}`}
                  className="space-y-3 rounded-md border border-border bg-surface p-3"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-foreground">
                        {section.title}
                      </p>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {sectionKindLabel(section.kind)} · {sectionSourceLabel(section.source)}
                      </p>
                    </div>
                    <div className="flex shrink-0 gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Move ${section.title} up`}
                        disabled={index === 0}
                        onClick={() => move(index, -1)}
                      >
                        <ArrowUp className="h-3.5 w-3.5" aria-hidden="true" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Move ${section.title} down`}
                        disabled={index === sections.length - 1}
                        onClick={() => move(index, 1)}
                      >
                        <ArrowDown className="h-3.5 w-3.5" aria-hidden="true" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Remove ${section.title}`}
                        onClick={() => remove(index)}
                      >
                        <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                      </Button>
                    </div>
                  </div>

                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="space-y-1.5">
                      <Label htmlFor={`section-title-${index}`}>Heading</Label>
                      <Input
                        id={`section-title-${index}`}
                        value={section.title}
                        onChange={(event) => update(index, { title: event.target.value })}
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor={`section-source-${index}`}>Data block</Label>
                      <Select
                        id={`section-source-${index}`}
                        value={section.source}
                        onChange={(event) =>
                          update(index, { source: event.target.value, figures: [] })
                        }
                      >
                        {vocabularies.section_sources.map((source) => (
                          <option key={source} value={source}>
                            {sectionSourceLabel(source)}
                          </option>
                        ))}
                      </Select>
                    </div>
                  </div>

                  {section.kind === KPI_GRID && section.source === HEADLINE_SOURCE ? (
                    <fieldset className="space-y-2">
                      <legend className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        Figures in this grid
                      </legend>
                      <p className="text-xs text-muted-foreground">
                        Choosing none prints every figure the block produces.
                      </p>
                      <div className="flex flex-wrap gap-x-4 gap-y-2">
                        {vocabularies.headline_figures.map((figure) => (
                          <label key={figure} className="flex items-center gap-2 text-sm">
                            <input
                              type="checkbox"
                              className="h-4 w-4 rounded border-input"
                              checked={section.figures.includes(figure)}
                              onChange={() => toggleFigure(index, figure)}
                            />
                            <span className="text-foreground">{headlineFigureLabel(figure)}</span>
                          </label>
                        ))}
                      </div>
                    </fieldset>
                  ) : (
                    <p className="text-xs text-muted-foreground">
                      This section prints the whole block its data source produces.
                    </p>
                  )}
                </li>
              ))}
            </ol>
          </div>

          <div className="space-y-1.5">
            <h3 className="text-sm font-semibold text-foreground">
              Printed on the document itself
            </h3>
            <div className="flex flex-wrap gap-1.5">
              {row.disclosures.map((disclosure) => (
                <Badge key={disclosure} variant="muted" title={disclosure}>
                  {disclosure.slice(0, 48)}…
                </Badge>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              The standing disclosures travel with the document wherever it goes. They are not
              edited from this dialog.
            </p>
          </div>

          <ChangeReasonField
            id="template-reason"
            value={reason}
            onChange={setReason}
            subject={`the ${reportTypeLabel(row.report_type).toLowerCase()} report's structure`}
            disabled={saving}
          />
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={!ready || saving}>
            {saving ? "Saving…" : "Save change"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
