import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import UploadPage from "./pages/UploadPage";
import SessionPage from "./pages/SessionPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* 기본 경로 → 업로드 페이지 */}
        <Route path="/" element={<Navigate to="/upload" replace />} />
        <Route path="/upload" element={<UploadPage />} />
        {/* 다음 주 구현 예정 */}
        <Route path="/session/:documentId" element={<SessionPage />} />
      </Routes>
    </BrowserRouter>
  );
}
