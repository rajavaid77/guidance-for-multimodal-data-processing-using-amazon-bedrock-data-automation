import { ExternalLink, LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";

interface PartUrl {
  url: string;
  content_type: string;
  expires_in: number;
  page: number | null;
}

/** Fetches a fresh short-lived link every time it is mounted; links are never cached. */
export function DocumentViewer({ claimId, partId, name }: { claimId: string; partId: number; name: string }) {
  const [link, setLink] = useState<PartUrl | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    api<PartUrl>(`/claims/${claimId}/parts/${partId}/url`)
      .then((r) => live && setLink(r))
      .catch((e) => live && setError((e as Error).message));
    return () => { live = false; };
  }, [claimId, partId]);

  if (error) return <div className="banner bad">{error}</div>;
  if (!link) return <p className="muted"><LoaderCircle size={14} className="spin" /> Loading document…</p>;
  if (link.content_type === "image/tiff") {
    return (
      <p>
        This browser cannot display TIFF files.{" "}
        <a href={link.url} target="_blank" rel="noreferrer noopener">Open in new tab <ExternalLink size={13} /></a>
      </p>
    );
  }
  const src = link.page && link.content_type === "application/pdf" ? `${link.url}#page=${link.page}` : link.url;
  return <iframe title={name} src={src} className="viewer" referrerPolicy="no-referrer" />;
}
