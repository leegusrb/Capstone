/**
 * 학습 세션 페이지 — 다음 주 구현 예정.
 * 지금은 placeholder로만 두고, 라우팅 오류가 나지 않도록 한다.
 */
import { useParams } from "react-router-dom";

export default function SessionPage() {
  const { documentId } = useParams();

  return (
    <div style={{ maxWidth: "700px", margin: "80px auto", padding: "0 20px" }}>
      <h1>학습 세션</h1>
      <p style={{ color: "#666" }}>
        Document ID: {documentId} — 세션 기능은 다음 주 구현 예정입니다.
      </p>
    </div>
  );
}
