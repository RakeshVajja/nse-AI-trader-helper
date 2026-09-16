import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NSE AI Trading Agent & Simulator",
  description:
    "AI-powered quantitative simulated trading platform for NSE equities and indices.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-background text-slate-200 antialiased font-sans flex flex-col">
        {children}
      </body>
    </html>
  );
}
