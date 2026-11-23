import { CloudUpload, FileText, Plus, X } from "lucide-react";
import { useRef } from "react";

export const ACCEPT = "application/pdf,image/png,image/jpeg,image/tiff";
export const MAX_BYTES = 20 * 1024 * 1024;

export function UploadTile({ label, file, onFile, onRemove }: {
  label: string;
  file?: File | null;
  onFile: (f: File) => void;
  onRemove?: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  if (file) {
    const tooBig = file.size > MAX_BYTES;
    return (
      <div className="tile filled">
        {onRemove && (
          <button type="button" className="icon-btn remove" aria-label={`Remove ${file.name}`} onClick={onRemove}>
            <X size={16} />
          </button>
        )}
        <FileText size={34} className="cloud" strokeWidth={1.5} />
        <span className="fname">{file.name}</span>
        <span className={tooBig ? "error-text" : "meta"}>{(file.size / 1024 / 1024).toFixed(1)} MB{tooBig ? " · too large" : ""}</span>
        <span className="muted">{label}</span>
      </div>
    );
  }
  return (
    <label className="tile">
      <CloudUpload size={38} className="cloud" strokeWidth={1.75} />
      <span>{label}</span>
      <span className="meta">Max 20 MB · PDF, PNG, JPG, TIFF</span>
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
          e.target.value = "";
        }}
      />
    </label>
  );
}

export function AddTile({ label, onFiles }: { label: string; onFiles: (files: File[]) => void }) {
  return (
    <label className="add-tile" title={label} aria-label={label}>
      <Plus size={28} />
      <input
        type="file"
        accept={ACCEPT}
        multiple
        style={{ display: "none" }}
        onChange={(e) => {
          onFiles(Array.from(e.target.files ?? []));
          e.target.value = "";
        }}
      />
    </label>
  );
}
