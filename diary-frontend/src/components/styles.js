export function tabStyle(active) {
  return {
    padding: "8px 14px",
    borderRadius: 8,
    border: active ? "1px solid #3b82f6" : "1px solid #ddd",
    background: active ? "#eff6ff" : "#fff",
    fontWeight: active ? 600 : 400,
    cursor: "pointer",
  };
}

export function chipStyle(active) {
  return {
    marginRight: 4,
    marginBottom: 4,
    padding: "2px 8px",
    borderRadius: 12,
    border: "1px solid #ddd",
    background: active ? "#e8f0fe" : "#fafafa",
    cursor: "pointer",
    fontSize: 12,
  };
}

export const preStyle = {
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
  background: "#f6f6f6",
  padding: 12,
  borderRadius: 8,
  fontSize: 13,
};
