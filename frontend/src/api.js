const BASE = 'http://localhost:8000/api/v1';

function getCurrentUserId() {
  try {
    return JSON.parse(localStorage.getItem('kg_user'))?.id || '';
  } catch {
    return '';
  }
}

function withAuthHeaders(headers = {}) {
  const userId = getCurrentUserId();
  return userId ? { ...headers, 'X-User-Id': userId } : headers;
}

async function req(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: withAuthHeaders({
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    }),
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
    return fetch(`${BASE}/documents/upload`, {
      method: 'POST',
      headers: withAuthHeaders(),
      body: form,
    })
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
  deleteDocument:      (id) => req(`/documents/${id}`, { method: 'DELETE' }),

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
  getSessionReport: (id) => req(`/sessions/${id}/report`),

  // 학생모드 Q&A
  askStudyTutor: (body) =>
    req('/study-chat/ask', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  // 음성 인식
  transcribeAudio: (audioBlob, topic) => {
    const form = new FormData();
    const ext = getAudioExtension(audioBlob.type);
    form.append('file', audioBlob, `teacher-mode.${ext}`);
    form.append('topic', topic || '');

    return fetch(`${BASE}/speech/transcribe`, {
      method: 'POST',
      headers: withAuthHeaders(),
      body: form,
    })
      .then(async res => {
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.detail || `HTTP ${res.status}`);
        }
        return res.json();
      });
  },
};

function getAudioExtension(mimeType = '') {
  if (mimeType.includes('wav')) return 'wav';
  if (mimeType.includes('mpeg') || mimeType.includes('mp3')) return 'mp3';
  if (mimeType.includes('mp4')) return 'm4a';
  return 'webm';
}

// API KG 노드/엣지 → KnowledgeGraph 컴포넌트 형식 변환 (centered subtree 트리 레이아웃)
export function layoutKGNodes(nodes, edges, width, height) {
  if (!nodes || nodes.length === 0) return [];

  const ids = nodes.map(n => n.id);
  const edgeList = (edges || [])
    .map(e => ({ src: e.source || e.from, tgt: e.target || e.to }))
    .filter(e => e.src !== e.tgt && ids.includes(e.src) && ids.includes(e.tgt));

  // 인접 리스트 & 진입 차수
  const childrenOf = Object.fromEntries(ids.map(id => [id, []]));
  const inDeg      = Object.fromEntries(ids.map(id => [id, 0]));
  edgeList.forEach(({ src, tgt }) => {
    if (!childrenOf[src].includes(tgt)) {
      childrenOf[src].push(tgt);
      inDeg[tgt]++;
    }
  });

  // 위상 정렬
  const tempInDeg = { ...inDeg };
  const queue = ids.filter(id => tempInDeg[id] === 0);
  const topoOrder = [];
  const seen = new Set(queue);
  while (queue.length > 0) {
    const curr = queue.shift();
    topoOrder.push(curr);
    for (const child of childrenOf[curr]) {
      tempInDeg[child]--;
      if (tempInDeg[child] === 0 && !seen.has(child)) {
        seen.add(child);
        queue.push(child);
      }
    }
  }
  ids.forEach(id => { if (!seen.has(id)) topoOrder.push(id); });

  // 레벨 결정
  const level = Object.fromEntries(ids.map(id => [id, 0]));
  topoOrder.forEach(id => {
    childrenOf[id].forEach(child => {
      level[child] = Math.max(level[child], level[id] + 1);
    });
  });

  const maxLevel = Math.max(...ids.map(id => level[id]), 0);
  const numLevels = maxLevel + 1;
  const roots = ids.filter(id => inDeg[id] === 0);
  if (roots.length === 0) roots.push(ids[0]);

  // ── Centered subtree x 배치 ─────────────────────────────
  // DFS로 리프에 순차 인덱스 부여 → 부모는 자식 인덱스의 중앙에 위치
  const estimateLabelWidth = (label) => {
    const text = String(label || '');
    if (!text) return 0;
    if (text.includes(' ')) {
      return Math.max(...text.split(/\s+/).map(part => part.length)) * 12;
    }
    return Math.min(text.length, 6) * 13;
  };

  const maxLabelWidth = Math.max(...nodes.map(n => estimateLabelWidth(n.id)), 72);
  const MIN_SPACING = Math.max(118, maxLabelWidth + 42); // 라벨 폭 + 여유
  const padX = Math.max(64, Math.ceil(MIN_SPACING / 2));
  const padY = 46;

  let leafIdx = 0;
  const xIdx = {};         // 노드별 수평 인덱스 (소수 가능)
  const dfsVisited = new Set();

  function dfs(id) {
    if (dfsVisited.has(id)) return;
    dfsVisited.add(id);

    // 현재 레벨보다 깊은 자식만 순회 (역방향 엣지·사이클 차단)
    const fwdChildren = childrenOf[id].filter(c => level[c] > level[id]);

    if (fwdChildren.length === 0) {
      // 리프: 순차 인덱스 배정
      xIdx[id] = leafIdx++;
    } else {
      fwdChildren.forEach(c => dfs(c));
      // 부모: 자식 인덱스 범위의 중앙
      const xs = fwdChildren.map(c => xIdx[c]).filter(x => x !== undefined);
      xIdx[id] = xs.length > 0
        ? (Math.min(...xs) + Math.max(...xs)) / 2
        : leafIdx++;
    }
  }

  roots.forEach(r => dfs(r));
  // 미방문 노드(고립) 처리
  ids.forEach(id => { if (xIdx[id] === undefined) xIdx[id] = leafIdx++; });

  // 수평: 리프 수 기반 동적 확장 / 수직: 레벨당 고정 간격
  const VERT_GAP = 150;
  const totalLeaves = Math.max(leafIdx, 1);
  const effW = Math.max(width,  padX * 2 + (totalLeaves - 1) * MIN_SPACING);
  const effH = Math.max(height, padY * 2 + maxLevel * VERT_GAP);

  const pos = {};
  ids.forEach(id => {
    const lx = padX + xIdx[id] * MIN_SPACING;
    const ly = maxLevel === 0
      ? effH / 2
      : padY + level[id] * VERT_GAP;
    pos[id] = { x: Math.round(lx), y: Math.round(ly) };
  });

  const layoutNodes = nodes.map(n => ({
    id: n.id,
    label: n.id,
    x: pos[n.id]?.x ?? Math.round(effW / 2),
    y: pos[n.id]?.y ?? Math.round(effH / 2),
    status: n.status || 'missing',
    checklist: n.checklist || [],
  }));

  return { nodes: layoutNodes, width: Math.ceil(effW), height: Math.ceil(effH) };
}

export function convertEdges(edges) {
  return (edges || []).map(e => ({ from: e.source, to: e.target }));
}

// misconception dict → 표시용 문자열
export function getMisconceptionText(m) {
  if (typeof m === 'string') return m;
  if (m.content && m.correction) {
    const prefix = m.node ? `[${m.node}] ` : '';
    return `${prefix}"${m.content}"라고 설명했지만, "${m.correction}"이 맞습니다.`;
  }
  return m.description || m.text || m.message || JSON.stringify(m);
}
