import { useState } from "react";
import { uploadDocument } from "../api/documents";

/**
 * PDF 업로드 + 처리 상태를 관리하는 커스텀 훅.
 *
 * 반환값:
 *   - upload(file): 업로드 실행 함수
 *   - uploadProgress: 파일 전송 진행률 (0~100)
 *   - status: "idle" | "uploading" | "processing" | "done" | "error"
 *   - result: 업로드 성공 시 서버 응답 { id, filename, chunk_count, ... }
 *   - error: 에러 메시지 문자열
 *   - reset: 상태 초기화 함수
 */
export function useFileUpload() {
  const [uploadProgress, setUploadProgress] = useState(0);
  const [status, setStatus] = useState("idle");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const upload = async (file) => {
    // 초기화
    setStatus("uploading");
    setUploadProgress(0);
    setResult(null);
    setError(null);

    try {
      // 파일 전송 중 (uploading)
      setStatus("uploading");
      const data = await uploadDocument(file, (percent) => {
        setUploadProgress(percent);
        // 100% 도달 후 서버 처리 중 상태로 전환
        if (percent === 100) setStatus("processing");
      });

      // 서버 처리 완료 (done)
      setResult(data);
      setStatus("done");
    } catch (err) {
      const message =
        err.response?.data?.detail || "업로드 중 오류가 발생했습니다.";
      setError(message);
      setStatus("error");
    }
  };

  const reset = () => {
    setUploadProgress(0);
    setStatus("idle");
    setResult(null);
    setError(null);
  };

  return { upload, uploadProgress, status, result, error, reset };
}
