import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { headers } from "next/headers";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host = requestHeaders.get("x-forwarded-host") ?? requestHeaders.get("host") ?? "localhost:3000";
  const protocol = requestHeaders.get("x-forwarded-proto") ?? (host.startsWith("localhost") ? "http" : "https");
  const siteUrl = new URL(`${protocol}://${host}`);

  return {
    metadataBase: siteUrl,
    title: "SciGuard Autopilot — Scientific Decision Control Plane",
    description:
      "DataHub-powered incident command center for evidence-gated scientific data and ML decisions.",
    openGraph: {
      title: "SciGuard Autopilot",
      description: "See silent scientific-data drift before it becomes a research decision.",
      type: "website",
      url: siteUrl,
      images: [{ url: "/og.png", width: 1731, height: 909, alt: "SciGuard scientific lineage and evidence trails" }],
    },
    twitter: {
      card: "summary_large_image",
      title: "SciGuard Autopilot",
      description: "Scientific decision control, powered by DataHub evidence.",
      images: ["/og.png"],
    },
  };
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
