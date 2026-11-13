"use client";

import { useState } from "react";
import type { CSSProperties, FormEvent } from "react";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

interface Citation {
  doc_id: string;
  filename: string;
  locator: string;
  score: number;
}

interface AnswerResponse {
  answer: string;
  citations: Citation[];
  abstained: boolean;
  reason?: string;
}

interface ConversationEntry {
  question: string;
  response: AnswerResponse | null;
  error: string | null;
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

export default function ChatPage() {
  const [question, setQuestion] = useState("");
  const [pending, setPending] = useState(false);
  const [conversation, setConversation] = useState<ConversationEntry[]>([]);

  async function ask(event: FormEvent) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || pending) return;
    setPending(true);
    const entry: ConversationEntry = {
      question: trimmed,
      response: null,
      error: null,
    };
    setQuestion("");
    setConversation((prev) => [entry, ...prev]);
    try {
      const res = await fetch(`${API_BASE}/answer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmed }),
      });
      if (res.status === 500) {
        entry.error =
          "The backend could not process the question (is the LLM configured?)";
      } else if (!res.ok) {
        entry.error = `Request failed with HTTP ${res.status}.`;
      } else {
        entry.response = (await res.json()) as AnswerResponse;
      }
    } catch {
      entry.error = `Backend unreachable at ${API_BASE}`;
    }
    setConversation((prev) => [...prev]);
    setPending(false);
  }

  return (
    <div>
      <h1>Chat</h1>
      <form onSubmit={ask}>
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask a question about your documents..."
          rows={3}
          style={{ width: "100%", boxSizing: "border-box" }}
        />
        <button type="submit" disabled={pending || !question.trim()}>
          Ask
        </button>
      </form>

      <div style={{ marginTop: 24 }}>
        {conversation.length === 0 && (
          <p style={{ color: "#6b7280" }}>
            No questions yet. Ask something to see grounded answers.
          </p>
        )}
        {conversation.map((entry, index) => (
          <div key={index} style={boxStyle}>
            <p>
              <strong>Q:</strong> {entry.question}
            </p>
            {entry.error && <p style={errorStyle}>{entry.error}</p>}
            {entry.response && entry.response.abstained && (
              <p style={{ color: "#92400e" }}>
                No sufficient evidence found (INSUFFICIENT_EVIDENCE)
                {entry.response.reason && (
                  <>
                    {" "}
                    &mdash; reason: <code>{entry.response.reason}</code>
                  </>
                )}
              </p>
            )}
            {entry.response && !entry.response.abstained && (
              <>
                <p>
                  <strong>A:</strong> {entry.response.answer}
                </p>
                <div>
                  <strong>Sources</strong>
                  {entry.response.citations.length === 0 ? (
                    <p style={{ color: "#6b7280" }}>No citations returned.</p>
                  ) : (
                    <ul>
                      {entry.response.citations.map((citation, cIndex) => (
                        <li key={cIndex}>
                          {citation.filename} &mdash; {citation.locator}{" "}
                          (score: {citation.score})
                        </li>
                      ))}
                    </ul>
                  )}
                  <p style={{ color: "#6b7280", fontSize: 12 }}>
                    The locator identifies the exact source section the answer
                    was drawn from.
                  </p>
                </div>
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
