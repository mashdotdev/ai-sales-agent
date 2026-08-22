"use client";

import { useRef, useState } from "react";

type SearchResult = {
  content: string;
  score: number;
  chunk_id: string;
  doc_id: string;
  doc_title: string;
  chunk_index: number | null;
};

/**
 * Phase 2's proof point: upload a document, then search it, and see real
 * relevance scores — before any agent (voice/email) depends on retrieval
 * working. See documents/phase2.md.
 */
export function KnowledgeSection() {
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<SearchResult[] | null>(null);

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || (!text.trim() && !file)) {
      setUploadMessage("Provide a title and either pasted text or a file.");
      return;
    }

    setUploading(true);
    setUploadMessage(null);
    try {
      const formData = new FormData();
      formData.set("title", title);
      if (file) formData.set("file", file);
      else formData.set("text", text);

      const res = await fetch("/api/knowledge/ingest", { method: "POST", body: formData });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? data.error ?? "Upload failed");

      setUploadMessage(`Ingested "${data.title}" — ${data.chunk_count} chunks.`);
      setTitle("");
      setText("");
      setFile(null);
    } catch (err) {
      setUploadMessage(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;

    setSearching(true);
    try {
      const res = await fetch(`/api/knowledge/search?q=${encodeURIComponent(query)}&top_k=5`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? data.error ?? "Search failed");
      setResults(data);
    } catch {
      setResults([]);
    } finally {
      setSearching(false);
    }
  }

  return (
    <section className="rounded border p-4">
      <h2 className="font-medium">Knowledge base</h2>
      <p className="mt-1 text-sm text-foreground/60">
        Upload a document, then search it — proves retrieval before any agent depends on it.
      </p>

      <form onSubmit={handleUpload} className="mt-4 flex flex-col gap-2">
        <input
          className="rounded border px-2 py-1.5 text-sm"
          placeholder="Document title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <textarea
          className="min-h-24 rounded border px-2 py-1.5 text-sm disabled:opacity-50"
          placeholder="Paste text here, or attach a file below"
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={Boolean(file)}
        />
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.txt,text/plain,application/pdf"
          className="hidden"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="rounded border px-3 py-1.5 text-sm"
          >
            Choose file
          </button>
          <span className="text-sm text-foreground/60">
            {file ? file.name : "No file chosen"}
          </span>
          {file && (
            <button
              type="button"
              onClick={() => {
                setFile(null);
                if (fileInputRef.current) fileInputRef.current.value = "";
              }}
              className="text-sm text-foreground/60 underline"
            >
              Clear
            </button>
          )}
        </div>
        <button
          type="submit"
          disabled={uploading}
          className="self-start rounded bg-foreground px-3 py-1.5 text-sm text-background disabled:opacity-50"
        >
          {uploading ? "Uploading…" : "Upload"}
        </button>
        {uploadMessage && <p className="text-sm text-foreground/70">{uploadMessage}</p>}
      </form>

      <form onSubmit={handleSearch} className="mt-6 flex gap-2 border-t pt-4">
        <input
          className="flex-1 rounded border px-2 py-1.5 text-sm"
          placeholder="Search the knowledge base…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button
          type="submit"
          disabled={searching}
          className="rounded border px-3 py-1.5 text-sm disabled:opacity-50"
        >
          {searching ? "Searching…" : "Search"}
        </button>
      </form>

      {results && (
        <ul className="mt-4 flex flex-col gap-2">
          {results.length === 0 && <li className="text-sm text-foreground/60">No results.</li>}
          {results.map((r) => (
            <li key={r.chunk_id} className="rounded border p-2 text-sm">
              <div className="flex items-center justify-between text-xs text-foreground/60">
                <span>{r.doc_title}</span>
                <span>score: {r.score.toFixed(3)}</span>
              </div>
              <p className="mt-1">{r.content}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
