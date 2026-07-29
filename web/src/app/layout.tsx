import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Find-Me-A-Job AI",
  description: "Find job opportunities near you — powered by AI",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
