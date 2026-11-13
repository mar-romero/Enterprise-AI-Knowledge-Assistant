"use client";

import { useCallback, useEffect, useState } from "react";
import type { ChangeEvent, CSSProperties, FormEvent } from "react";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

interface DocumentMetadata {
  id: string;
  filename: string;
  sha256: string;
  size: number;
  uploaded_at: string;
  duplicate: boolean;
}

const boxStyle: CSSProperties = {
  border: "1px solid #e5e7eb",
  borderRadius: 6,
  padding: 12,
  marginBottom: 16,
  background: "#f9fafb",
};

const errorStyle: CSSProperties = {
  color: "#b91c1c",
  marginBottom: 16,
};

const successStyle: CSSProperties = {
  color: "#166534",
  marginBottom: 16,
};

function friendlyError(status: number): string {
  if (status === 400) return "Upload rejected (HTTP 400): the request or file content was invalid.";
  if (status === 413) return "File too large (HTTP 413).";
  if (status === 500) return "The backend failed while processing the upload (HTTP 500).";
  return `Request failed with HTTP ${status}.`;
}

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<DocumentMetadata[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploaded, setUploaded] = useState<DocumentMetadata | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(false);

  const loadDocuments = useCallback(async () => {
    setLoading(true);
    setListError(null);
    try {
      const res = await fetch(`${API_BASE}/documents`);
      if (!res.ok) {
        setListError(`Failed to list documents (HTTP ${res.status}).`);
      } else {
        setDocuments((await res.json()) as DocumentMetadata[]);
      }
    } catch {
      setListError(`Backend unreachable at ${API_BASE}`);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadDocuments();
  }, [loadDocuments]);

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files && event.target.files[0] ? event.target.files[0] : null);
  }

  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!file || uploading) return;
    setUploading(true);
    setUploadError(null);
    setUploaded(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`${API_BASE}/documents`, { method: "POST", body: form });
      if (!res.ok) {
        setUploadError(friendlyError(res.status));
      } else {
        setUploaded((await res.json()) as DocumentMetadata);
        await loadDocuments();
      }
    } catch {
      setUploadError(`Backend unreachable at ${API_BASE}`);
    }
    setUploading(false);
  }

  return (
    <div>
      <h1>Documents</h1>

      <section style={boxStyle}>
        <h2 style={{ marginTop: 0 }}>Upload</h2>
        <form onSubmit={upload}>
          <input type="file" onChange={onFileChange} />
          <button type="submit" disabled={!file || uploading}>
            Upload
          </button>
        </form>
        {uploadError && <p style={errorStyle}>{uploadError}</p>}
        {uploaded && (
          <div style={successStyle}>
            <p>
              <strong>Registered:</strong> {uploaded.filename} (id: {uploaded.id})
            </p>
            <ul style={{ fontSize: 12 }}>
              <li>sha256: {uploaded.sha256}</li>
              <li>size: {uploaded.size} bytes</li>
              <li>
                duplicate: {String(uploaded.duplicate)}
                {uploaded.duplicate && " (already registered — deduplicated)"}
              </li>
            </ul>
          </div>
        )}
      </section>

      <section>
        <h2>
          Registered documents{" "}
          <button onClick={loadDocuments} disabled={loading}>
            Refresh
          </button>
        </h2>
        {listError && <p style={errorStyle}>{listError}</p>}
        {documents === null && !listError && (
          <p style={{ color: "#6b7280" }}>Loading…</p>
        )}
        {documents !== null && documents.length === 0 && (
          <p style={{ color: "#6b7280" }}>No documents registered yet.</p>
        )}
        {documents !== null && documents.length > 0 && (
          <ul>
            {documents.map((doc) => (
              <li key={doc.id} style={{ marginBottom: 8 }}>
                <strong>{doc.filename}</strong>
                <div style={{ fontSize: 12, color: "#374151" }}>
                  id: {doc.id} · sha256: {doc.sha256} · size: {doc.size} bytes ·
                  uploaded_at: {doc.uploaded_at} · duplicate:{" "}
                  {String(doc.duplicate)}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
