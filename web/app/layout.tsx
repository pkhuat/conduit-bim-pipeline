import "./globals.css";
import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Tubender — Conduit Fabrication",
  description: "Turn a BIM/IFC model into a machine-ready conduit fabrication package.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="topbar">
          <div className="inner">
            <Link href="/" className="brand"><span className="dot" />Tubender</Link>
            <nav>
              <Link href="/">Jobs</Link>
              <Link href="/bend">New bend</Link>
            </nav>
            <span className="spacer" />
            <span className="env">Fabrication Console</span>
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
