import { useNavigate } from "react-router-dom";
import FileUpload from "../components/upload/FileUpload";
import LoadingSpinner from "../components/common/LoadingSpinner";
import { useFileUpload } from "../hooks/useFileUpload";

export default function UploadPage() {
  const navigate = useNavigate();
  const { upload, uploadProgress, status, result, error, reset } =
    useFileUpload();

  const handleFileSelect = async (file) => {
    await upload(file);
  };

  // 업로드 완료 후 세션 페이지로 이동
  const handleStartSession = () => {
    if (result?.id) {
      navigate(`/session/${result.id}`);
    }
  };

  return (
    <div style={{ maxWidth: "600px", margin: "80px auto", padding: "0 20px" }}>
      <h1 style={{ fontSize: "24px", marginBottom: "8px" }}>
        학습 자료 업로드
      </h1>
      <p style={{ color: "#666", marginBottom: "32px" }}>
        공부할 PDF를 올리면 AI가 내용을 분석하고 학습 세션을 시작합니다.
      </p>

      {/* 업로드 영역 */}
      <FileUpload
        onFileSelect={handleFileSelect}
        disabled={status === "uploading" || status === "processing"}
      />

      {/* 진행 상태 표시 */}
      {status === "uploading" && (
        <div style={{ marginTop: "24px" }}>
          <p style={{ fontSize: "14px", color: "#444", marginBottom: "8px" }}>
            파일 전송 중... {uploadProgress}%
          </p>
          <div
            style={{
              height: "6px",
              background: "#e0e0e0",
              borderRadius: "3px",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                width: `${uploadProgress}%`,
                height: "100%",
                background: "#4a90e2",
                transition: "width 0.3s",
              }}
            />
          </div>
        </div>
      )}

      {status === "processing" && (
        <div style={{ marginTop: "24px" }}>
          <LoadingSpinner message="PDF 분석 중입니다. 잠시만 기다려 주세요..." />
        </div>
      )}

      {/* 완료 */}
      {status === "done" && result && (
        <div
          style={{
            marginTop: "24px",
            padding: "20px",
            background: "#f0fff4",
            border: "1px solid #6fcf97",
            borderRadius: "8px",
          }}
        >
          <p style={{ fontWeight: "bold", color: "#219653" }}>
            ✅ 업로드 완료
          </p>
          <p style={{ fontSize: "14px", color: "#555", marginTop: "6px" }}>
            파일명: {result.filename}
          </p>
          <p style={{ fontSize: "14px", color: "#555" }}>
            생성된 청크: {result.chunk_count}개
          </p>
          <div style={{ marginTop: "16px", display: "flex", gap: "10px" }}>
            <button
              onClick={handleStartSession}
              style={{
                padding: "10px 20px",
                background: "#4a90e2",
                color: "#fff",
                border: "none",
                borderRadius: "6px",
                cursor: "pointer",
                fontSize: "14px",
              }}
            >
              학습 시작하기 →
            </button>
            <button
              onClick={reset}
              style={{
                padding: "10px 20px",
                background: "#fff",
                color: "#444",
                border: "1px solid #ccc",
                borderRadius: "6px",
                cursor: "pointer",
                fontSize: "14px",
              }}
            >
              다른 파일 올리기
            </button>
          </div>
        </div>
      )}

      {/* 에러 */}
      {status === "error" && (
        <div
          style={{
            marginTop: "24px",
            padding: "16px",
            background: "#fff5f5",
            border: "1px solid #fc8181",
            borderRadius: "8px",
          }}
        >
          <p style={{ color: "#c53030", fontWeight: "bold" }}>
            ❌ 업로드 실패
          </p>
          <p style={{ fontSize: "14px", color: "#555", marginTop: "4px" }}>
            {error}
          </p>
          <button
            onClick={reset}
            style={{
              marginTop: "12px",
              padding: "8px 16px",
              background: "#fff",
              color: "#444",
              border: "1px solid #ccc",
              borderRadius: "6px",
              cursor: "pointer",
              fontSize: "13px",
            }}
          >
            다시 시도
          </button>
        </div>
      )}
    </div>
  );
}
