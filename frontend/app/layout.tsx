import type { CSSProperties, ReactNode } from "react";
import Link from "next/link";

export const metadata = {
  title: "Enterprise AI Copilot",
};

const bodyStyle: CSSProperties = {
  fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif",
  color: "#1f2937",
  lineHeight: 1.5,
  margin: 0,
  padding: 24,
};

const headerStyle: CSSProperties = {
  borderBottom: "1px solid #e5e7eb",
  paddingBottom: 12,
  marginBottom: 24,
};

const navStyle: CSSProperties = {
  display: "flex",
  gap: 16,
  marginTop: 8,
};

const linkStyle: CSSProperties = {
  color: "#2563eb",
  textDecoration: "none",
};

const containerStyle: CSSProperties = {
  maxWidth: 720,
  margin: "0 auto",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body style={bodyStyle}>
        <div style={containerStyle}>
          <header style={headerStyle}>
            <strong>Enterprise AI Copilot</strong>
            <nav style={navStyle}>
              <Link href="/" style={linkStyle}>
                Chat
              </Link>
              <Link href="/documents" style={linkStyle}>
                Documents
              </Link>
            </nav>
          </header>
          <main>{children}</main>
        </div>
      </body>
    </html>
  );
}
