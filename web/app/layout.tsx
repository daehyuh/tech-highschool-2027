import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "특성화고 입시 데이터랩",
  description: "대학별 특성화고 전형 입시결과를 성적과 희망 학과·계열로 탐색하는 상담용 데이터 플랫폼",
  metadataBase: new URL("https://vocational-admissions-lab.daehyuh.chatgpt.site"),
  openGraph: {
    title: "특성화고 입시 데이터랩",
    description: "성적과 희망 학과로 찾는 대학 입결",
    type: "website",
    images: [{ url: "/og.png", width: 1733, height: 907, alt: "특성화고 입시 데이터랩" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "특성화고 입시 데이터랩",
    description: "성적과 희망 학과로 찾는 대학 입결",
    images: ["/og.png"],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="ko"><body>{children}</body></html>;
}
