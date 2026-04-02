import { useRef } from "react";

/**
 * PDF 파일 선택 + 드래그앤드롭 업로드 컴포넌트.
 *
 * Props:
 *   - onFileSelect(file): 파일 선택 시 호출되는 콜백
 *   - disabled: 업로드 중 비활성화 여부
 */
export default function FileUpload({ onFileSelect, disabled }) {
  const inputRef = useRef(null);

  // 파일 선택 처리 (input 또는 드래그)
  const handleFile = (file) => {
    if (!file) return;
    if (!file.name.endsWith(".pdf")) {
      alert("PDF 파일만 업로드할 수 있습니다.");
      return;
    }
    onFileSelect(file);
  };

  // 드래그오버: 기본 동작 막기
  const handleDragOver = (e) => {
    e.preventDefault();
  };

  // 드롭 처리
  const handleDrop = (e) => {
    e.preventDefault();
    if (disabled) return;
    const file = e.dataTransfer.files?.[0];
    handleFile(file);
  };

  return (
    <div
      onClick={() => !disabled && inputRef.current?.click()}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      style={{
        border: "2px dashed #4a90e2",
        borderRadius: "12px",
        padding: "60px 40px",
        textAlign: "center",
        cursor: disabled ? "not-allowed" : "pointer",
        background: disabled ? "#f5f5f5" : "#fafcff",
        transition: "background 0.2s",
      }}
    >
      <p style={{ fontSize: "16px", color: "#444", marginBottom: "8px" }}>
        📄 PDF 파일을 드래그하거나 클릭해서 선택하세요
      </p>
      <p style={{ fontSize: "13px", color: "#999" }}>최대 20MB</p>

      {/* 숨겨진 input */}
      <input
        ref={inputRef}
        type="file"
        accept=".pdf"
        style={{ display: "none" }}
        onChange={(e) => handleFile(e.target.files?.[0])}
        disabled={disabled}
      />
    </div>
  );
}
