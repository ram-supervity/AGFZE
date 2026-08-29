"use client";

import { FileText, Maximize2, ZoomIn, ZoomOut } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

export interface PageViewerProps {
  filename: string;
  pageUrls: string[];
  sourceUrl: string | null;
  contentType: string;
}

const ZOOM_ = [0.75, 1, 1.25, 1.5, 2] as const;

/**
 * Shows the page images the extraction pass already produced. Nothing is rendered from the
 * source file in the browser: the same images the model read are the images the reviewer sees,
 * and each arrives through a short-lived signed URL.
 */
export function PageViewer({ filename, pageUrls, sourceUrl, contentType }: PageViewerProps) {
  const [zoomIndex, setZoomIndex] = useState(1);
  const zoom = ZOOM_[zoomIndex];

  if (pageUrls.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 rounded-lg border border-dashed border-border bg-surface px-6 py-16 text-center">
        <FileText className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
        <div className="space-y-1.5">
          <p className="text-sm font-medium text-foreground">No page preview for this file</p>
          <p className="max-w-sm text-sm text-muted-foreground">
            {contentType.includes("sheet") || contentType.includes("csv")
              ? "Spreadsheets are read as data rather than rendered as pages."
              : "This file type has no page image. Open the original to read it."}
          </p>
        </div>
        {sourceUrl ? (
          <Button asChild variant="outline" size="sm">
            <a href={sourceUrl} target="_blank" rel="noopener noreferrer">
              Open the original file
            </a>
          </Button>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col rounded-lg border border-border bg-card">
      <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
        <p className="truncate text-sm font-medium text-foreground">
          {pageUrls.length} page{pageUrls.length === 1 ? "" : "s"}
        </p>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            aria-label="Zoom out"
            disabled={zoomIndex === 0}
            onClick={() => setZoomIndex((index) => Math.max(0, index - 1))}
          >
            <ZoomOut aria-hidden="true" />
          </Button>
          <span className="w-12 text-center text-xs tabular-nums text-muted-foreground">
            {Math.round(zoom * 100)}%
          </span>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Zoom in"
            disabled={zoomIndex === ZOOM_.length - 1}
            onClick={() => setZoomIndex((index) => Math.min(ZOOM_.length - 1, index + 1))}
          >
            <ZoomIn aria-hidden="true" />
          </Button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto bg-surface p-3">
        <div className="mx-auto flex flex-col gap-4" style={{ width: `${zoom * 100}%` }}>
          {pageUrls.map((url, index) => (
            <Dialog key={url}>
              <DialogTrigger asChild>
                <button
                  type="button"
                  className="group relative block w-full overflow-hidden rounded-md border border-border bg-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={url}
                    alt={`Page ${index + 1} of ${filename}`}
                    className="w-full"
                    loading={index === 0 ? "eager" : "lazy"}
                  />
                  <span className="absolute left-2 top-2 rounded bg-primary/85 px-1.5 py-0.5 text-[10px] font-medium text-primary-foreground">
                    Page {index + 1}
                  </span>
                  <span className="absolute right-2 top-2 rounded bg-primary/85 p-1 text-primary-foreground opacity-0 transition-opacity group-hover:opacity-100">
                    <Maximize2 className="h-3 w-3" aria-hidden="true" />
                  </span>
                </button>
              </DialogTrigger>
              <DialogContent>
                <DialogTitle>
                  {filename} — page {index + 1}
                </DialogTitle>
                <DialogDescription className="sr-only">
                  Full-size view of page {index + 1}.
                </DialogDescription>
                <div className="min-h-0 flex-1 overflow-auto rounded-md border border-border bg-surface">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={url} alt={`Page ${index + 1} of ${filename}`} className="w-full" />
                </div>
              </DialogContent>
            </Dialog>
          ))}
        </div>
      </div>
    </div>
  );
}
