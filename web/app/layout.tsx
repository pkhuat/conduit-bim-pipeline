import "./globals.css";
import Link from "next/link";
import type { Metadata } from "next";
import { IBM_Plex_Sans, IBM_Plex_Mono } from "next/font/google";

const sans = IBM_Plex_Sans({
  subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-sans", display: "swap",
});
const mono = IBM_Plex_Mono({
  subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-mono", display: "swap",
});

export const metadata: Metadata = {
  title: "Tubender — Conduit Fabrication",
  description: "Turn a BIM/IFC model into a machine-ready conduit fabrication package.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body>
        <header className="topbar">
          <div className="inner">
            <Link href="/" className="brand">
              <img src="/tubender-mark.svg" alt="" width={26} height={26} aria-hidden="true" />Tubender
            </Link>
            <nav>
              <Link href="/">Jobs</Link>
              <Link href="/bend">New bend</Link>
            </nav>
            <span className="spacer" />
            <span className="env"><span className="dotlive" aria-hidden="true" />Fabrication Console</span>
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
