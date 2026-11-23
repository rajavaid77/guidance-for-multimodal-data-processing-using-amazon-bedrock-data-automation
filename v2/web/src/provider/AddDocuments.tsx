import { LoaderCircle } from "lucide-react";
import { useState } from "react";
import { api, putFile } from "../api";
import { Modal } from "../components/Modal";
import { AddTile, MAX_BYTES, UploadTile } from "../components/UploadTile";

const MAX_FILES = 10;

interface BatchResponse {
  claim_id: string;
  batch_id: string;
  uploads: { key: string; upload_url: string; content_type: string }[];
}

export function AddDocuments({ claimId, onClose, onDone }: { claimId: string; onClose: () => void; onDone: () => void }) {
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const tooBig = files.some((f) => f.size > MAX_BYTES);

  async function submit() {
    setError("");
    try {
      setBusy("Preparing…");
      const batch = await api<BatchResponse>(`/claims/${claimId}/batches`, {
        method: "POST",
        body: { documents: files.map((f) => ({ file_name: f.name, content_type: f.type || "application/pdf" })) },
      });
      for (let i = 0; i < files.length; i++) {
        setBusy(`Uploading ${i + 1} of ${files.length}…`);
        await putFile(batch.uploads[i].upload_url, files[i], batch.uploads[i].content_type);
      }
      setBusy("Submitting…");
      await api(`/claims/${claimId}/batches/${batch.batch_id}/submit`, { method: "POST", body: {} });
      onDone();
    } catch (err) {
      setError((err as Error).message);
      setBusy("");
    }
  }

  const add = (more: File[]) => setFiles((cur) => [...cur, ...more].slice(0, MAX_FILES));
  return (
    <Modal title="Add documents" onClose={busy ? () => undefined : onClose}>
      <p className="muted" style={{ marginTop: 0 }}>
        Upload up to {MAX_FILES} files (PDF, PNG, JPG or TIFF, max 20 MB each). A single file can hold several documents.
        They are read automatically and added to this claim.
      </p>
      <div className="tiles">
        {files.map((f, i) => (
          <UploadTile key={`${f.name}-${i}`} label="Additional document" file={f} onFile={() => undefined}
                      onRemove={busy ? undefined : () => setFiles((cur) => cur.filter((_, j) => j !== i))} />
        ))}
        {files.length === 0 && <UploadTile label="Upload a document" onFile={(f) => add([f])} />}
        {files.length > 0 && files.length < MAX_FILES && !busy && <AddTile label="Add more files" onFiles={add} />}
      </div>
      {tooBig && <p className="error-text">One or more files are larger than 20 MB.</p>}
      {error && <div className="banner bad" style={{ marginTop: 12 }}>{error}</div>}
      <div className="modal-actions">
        <button className="btn quiet" onClick={onClose} disabled={!!busy}>Cancel</button>
        <button className="btn" onClick={submit} disabled={files.length === 0 || tooBig || !!busy}>
          {busy ? <><LoaderCircle size={16} className="spin" /> {busy}</> : "Upload"}
        </button>
      </div>
    </Modal>
  );
}
