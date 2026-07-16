import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Conduit Pipeline",
  description: "Turn a BIM/IFC model into a machine-ready conduit fabrication package.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
