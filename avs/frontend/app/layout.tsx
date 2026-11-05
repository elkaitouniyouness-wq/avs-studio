import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "../lib/ui";

export const metadata: Metadata = {
  title: "AI Video Automation Studio",
  description: "Créez et publiez vos vidéos YouTube avec l'IA",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/icons/icon-192.png", apple: "/icons/apple-touch-icon.png" },
  appleWebApp: { capable: true, title: "Video Studio", statusBarStyle: "black-translucent" },
};
export const viewport: Viewport = { themeColor: "#4f46e5", width: "device-width", initialScale: 1, viewportFit: "cover" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr" data-theme="dark">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
