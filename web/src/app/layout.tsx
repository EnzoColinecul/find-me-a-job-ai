import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";

// Inter, self-hosted from a vendored variable woff2 (latin subset, wght axis).
// Deliberately next/font/local rather than next/font/google: the Google loader
// fetches from fonts.googleapis.com at build time, which makes every CI build
// network-dependent. This file is committed, so builds are hermetic.
//
// `display: swap` plus next/font's automatic size-adjust fallback metrics means
// no layout shift while the face loads.
const inter = localFont({
  src: "../fonts/inter-latin-wght-normal.woff2",
  weight: "100 900",
  style: "normal",
  display: "swap",
  variable: "--font-inter",
  fallback: ["system-ui", "-apple-system", "sans-serif"],
});

export const metadata: Metadata = {
  title: "Find Me a Job AI",
  description: "Your next job, found street by street.",
  icons: {
    icon: "/favicon.ico",
    apple: "/apple-icon.png",
  },
};

export const viewport: Viewport = {
  // The one legitimate literal: Next's viewport metadata is emitted before any
  // stylesheet loads, so it can't read --color-paper. Keep in sync with it.
  themeColor: "#f6f5f2",
  colorScheme: "light",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={inter.variable}>
      <body>{children}</body>
    </html>
  );
}
