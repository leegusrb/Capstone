const BASE = 'http://localhost:8000/api/v1';

async function req(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export const api = {
  // 문서
  uploadDocument: (file) => {
    const form = new FormData();
    form.append('file', file);
    return fetch(`${BASE}/documents/upload`, { method: 'POST', body: form })
      .then(async res => {
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.detail || `HTTP ${res.status}`);
        }
        return res.json();
      });
  },
  getDocument:         (id) => req(`/documents/${id}`),
  getDocuments:        ()   => req('/documents'),
  getDocumentSessions: (id) => req(`/documents/${id}/sessions`),

  // 지식 그래프
  getKG:     (id) => req(`/knowledge-graphs/${id}`),
  getUserKG: (id) => req(`/knowledge-graphs/${id}/user`),

  // 세션
  startSession: (document_id, topic) =>
    req('/sessions/start', {
      method: 'POST',
      body: JSON.stringify({ document_id, topic }),
    }),
  processTurn: (body) =>
    req('/sessions/turn', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  endSession: (body) =>
    req('/sessions/end', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
};

// API KG 노드/엣지 → KnowledgeGraph 컴포넌트 형식 변환
export function layoutKGNodes(nodes, width, height) {
  if (!nodes || nodes.length === 0) return [];
  const cx = width / 2, cy = height / 2;
  const r = Math.min(width, height) * 0.36;
  return nodes.map((node, i, arr) => ({
    id: node.id,
    label: node.id.length > 8 ? node.id.slice(0, 7) + '…' : node.id,
    x: Math.round(cx + Math.cos((i / arr.length) * 2 * Math.PI - Math.PI / 2) * r),
    y: Math.round(cy + Math.sin((i / arr.length) * 2 * Math.PI - Math.PI / 2) * r),
    status: node.status || 'missing',
    checklist: node.checklist_result || [],
  }));
}

export function convertEdges(edges) {
  return (edges || []).map(e => ({ from: e.source, to: e.target }));
}

// misconception dict → 표시용 문자열
export function getMisconceptionText(m) {
  if (typeof m === 'string') return m;
  return m.description || m.text || m.message || JSON.stringify(m);
}
