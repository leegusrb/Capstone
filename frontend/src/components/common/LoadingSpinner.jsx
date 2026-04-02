/**
 * 로딩 스피너 컴포넌트.
 * @param {string} message - 스피너 아래 표시할 텍스트 (선택)
 */
export default function LoadingSpinner({ message }) {
  return (
    <div style={{ textAlign: "center", padding: "20px" }}>
      <div
        style={{
          width: "36px",
          height: "36px",
          border: "4px solid #e0e0e0",
          borderTop: "4px solid #4a90e2",
          borderRadius: "50%",
          animation: "spin 0.8s linear infinite",
          margin: "0 auto",
        }}
      />
      {message && (
        <p style={{ marginTop: "12px", color: "#666", fontSize: "14px" }}>
          {message}
        </p>
      )}
      <style>{`
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
