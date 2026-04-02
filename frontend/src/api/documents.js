import axios from "axios";

// axios 기본 설정
const api = axios.create({
  baseURL: "/api/v1",   // vite proxy를 통해 백엔드로 전달됨
  timeout: 60000,       // PDF 처리 시간을 고려해 60초로 설정
});

/**
 * PDF 파일을 업로드하고 처리를 요청한다.
 *
 * @param {File} file - 업로드할 PDF 파일 객체
 * @param {function} onUploadProgress - 업로드 진행률 콜백 (0~100)
 * @returns {Promise<{ id, filename, status, chunk_count, created_at }>}
 */
export async function uploadDocument(file, onUploadProgress) {
  const formData = new FormData();
  formData.append("file", file);

  const response = await api.post("/documents/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" },
    onUploadProgress: (progressEvent) => {
      if (onUploadProgress && progressEvent.total) {
        const percent = Math.round(
          (progressEvent.loaded * 100) / progressEvent.total
        );
        onUploadProgress(percent);
      }
    },
  });

  return response.data;
}

/**
 * Document 처리 상태를 조회한다.
 *
 * @param {number} documentId
 * @returns {Promise<{ id, filename, status, chunk_count, created_at }>}
 */
export async function getDocumentStatus(documentId) {
  const response = await api.get(`/documents/${documentId}`);
  return response.data;
}
