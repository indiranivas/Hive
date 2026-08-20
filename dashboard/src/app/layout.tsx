import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Shell } from "@/components/Shell";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Hive — Team Knowledge",
  description:
    "A live, sourced view of your team's work trail: pulse, status, expertise and knowledge gaps.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // The inline script below stamps data-theme before React hydrates, so the
    // server and client markup differ on <html> by design.
    <html
      lang="en"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} h-full`}
    >
      <head>
        {/* Apply the stored theme before first paint so there is no flash of the
            wrong palette. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var t=localStorage.getItem('hive-theme');if(t){document.documentElement.dataset.theme=t}}catch(e){}`,
          }}
        />
      </head>
      <body className="min-h-full antialiased">
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
