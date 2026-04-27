export default function DonutChart({ percentage, size = 140, color = '#3b82f6', label }) {
  const r = (size - 20) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const circumference = 2 * Math.PI * r;
  const offset = circumference - (percentage / 100) * circumference;

  return (
    <div style={{ position: 'relative', width: size, height: size, flexShrink: 0 }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <defs>
          <linearGradient id="donut-grad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={color}/>
            <stop offset="100%" stopColor={color} stopOpacity="0.6"/>
          </linearGradient>
        </defs>
        {/* Track */}
        <circle
          cx={cx} cy={cy} r={r}
          fill="none"
          stroke="#21262d"
          strokeWidth={12}
        />
        {/* Fill */}
        <circle
          cx={cx} cy={cy} r={r}
          fill="none"
          stroke="url(#donut-grad)"
          strokeWidth={12}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{ transition: 'stroke-dashoffset 1s cubic-bezier(0.4,0,0.2,1)' }}
        />
      </svg>
      {/* Center text */}
      <div style={{
        position: 'absolute',
        inset: 0,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 2,
      }}>
        <span style={{ fontSize: size < 120 ? 18 : 22, fontWeight: 800, color: '#e6edf3', lineHeight: 1 }}>
          {percentage}%
        </span>
        {label && (
          <span style={{ fontSize: 10, color: '#8b949e', textAlign: 'center', maxWidth: 60 }}>
            {label}
          </span>
        )}
      </div>
    </div>
  );
}
